import re
from itertools import groupby
from odoo import _, api, models
from odoo.tools import html2plaintext


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _mail_parser_custom(self, model, thread_id, custom_values, user_id, alias_id, message_dict):
        """
        Prepare custom value from email
        """
        original_custom_values = custom_values.copy()
        message = message_dict.get('body')
        if alias_id and alias_id.mail_parser_ids:
            mail_parser_by_model = {}
            for models_id, grouped_lines in groupby(alias_id.mail_parser_ids, key=lambda l: l.models_id.id):
                mail_parser_by_model[models_id] = self.env['mail.parser'].concat(*grouped_lines)
            if mail_parser_by_model:
                model_vals = {}
                domain_vals = {}

                for model_id, parser_id in mail_parser_by_model.items():
                    model_vals = {}
                    domain_vals = {}
                    for parser in parser_id:
                        email_body = str(message)
                        tags_to_replace = ["<b>", "</b>"]
                        for tag in tags_to_replace:
                            email_body = email_body.replace(tag, "")
                        email_body = html2plaintext(email_body)
                        regex_match_value = self._get_value_from_regex_condition(parser.regex_condition, email_body)
                        if regex_match_value and parser.field_id.name:
                            model_vals[parser.field_id.name] = regex_match_value
                            if parser.should_be_unique:
                                domain_vals[parser.field_id.name] = regex_match_value or ''
                        else:
                            if parser.default_value and parser.field_id.name:
                                model_vals[parser.field_id.name] = parser.default_value
                                if parser.should_be_unique:
                                    domain_vals[parser.field_id.name] = parser.default_value or ''
                            else:
                                continue  # no default value set on this field

                # mail.thread.message_new (base) unconditionally overwrites the
                # primary email field with msg_dict['email_from'] *after* applying
                # custom_values, so we must update message_dict here to make the
                # parsed address survive. The field name varies by model (e.g.
                # 'email_from' on crm.lead, 'email' elsewhere), so check both.
                parsed_email = model_vals.get('email_from') or model_vals.get('email')
                if parsed_email and message_dict.get('email_from'):
                    message_dict['email_from'] = parsed_email
                custom_values.update(model_vals)
                return custom_values, message_dict, domain_vals
        return custom_values, message_dict, {}


    def _prepared_domain_from_dict(self, domain_vals):
        """
        Prepared domain from dictionary
        """
        domain = []
        for key, value in domain_vals.items():
            domain.append((key,'=', value))
        return domain


    @api.model
    def _message_route_process(self, message, message_dict, routes):
        """
        Method overwrite from
        URL: https://github.com/odoo/odoo/blob/69b1993fb45b76110c24f5189a0ecfe9eb59a2aa/addons/mail/models/mail_thread.py#L1130
        """
        if not message_dict['message_type'] == 'email':
            return super()._message_route_process(message, message_dict, routes)
        
        self = self.with_context(attachments_mime_plainxml=True)  # import XML attachments as text
        # postpone setting message_dict.partner_ids after message_post, to avoid double notifications
        original_partner_ids = message_dict.pop('partner_ids', [])
        thread_id = False
        custom_parser_value = {}
        # raise UserError(message)
        for model, thread_id, custom_values, user_id, alias in routes or ():
            subtype_id = False
            related_user = self.env['res.users'].browse(user_id)
            Model = self.env[model].with_context(mail_create_nosubscribe=True, mail_create_nolog=True)
            if not (thread_id and hasattr(Model, 'message_update') or hasattr(Model, 'message_new')):
                raise ValueError(
                    "Undeliverable mail with Message-Id %s, model %s does not accept incoming emails" %
                    (message_dict['message_id'], model)
                )
                
            if alias.mail_parser_ids:
                custom_parser_value, custom_message_dict, domain_vals = self._mail_parser_custom(
                                        model, 
                                        thread_id, 
                                        custom_values, 
                                        user_id, alias,
                                        message_dict)
                custom_values = custom_parser_value
                message_dict = custom_message_dict
                domain = self._prepared_domain_from_dict(domain_vals)
                existing_record_id = Model.search(domain, limit=1) if domain else Model.browse()
                Model = Model.with_context(
                            custom_parser_value=custom_parser_value,
                            alias_id=alias,
                            existing_record_id=existing_record_id)
                if existing_record_id:
                    thread_id = existing_record_id.id

            # disabled subscriptions during message_new/update to avoid having the system user running the
            # email gateway become a follower of all inbound messages
            ModelCtx = Model.with_user(related_user).sudo()
            if thread_id and hasattr(ModelCtx, 'message_update'):
                thread = ModelCtx.browse(thread_id)
                thread.message_update(message_dict)
            else:
                # if a new thread is created, parent is irrelevant
                message_dict.pop('parent_id', None)
                thread = ModelCtx.message_new(message_dict, custom_values)
                thread_id = thread.id
                subtype_id = thread._creation_subtype().id

            # replies to internal message are considered as notes, but parent message
            # author is added in recipients to ensure they are notified of a private answer
            parent_message = False
            if message_dict.get('parent_id'):
                parent_message = self.env['mail.message'].sudo().browse(message_dict['parent_id'])
            partner_ids = []
            if not subtype_id:
                if message_dict.get('is_internal'):
                    subtype_id = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note')
                    if parent_message and parent_message.author_id:
                        partner_ids = [parent_message.author_id.id]
                else:
                    subtype_id = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_comment')

            post_params = dict(subtype_id=subtype_id, partner_ids=partner_ids, **message_dict)
            # remove computational values not stored on mail.message and avoid warnings when creating it
            for x in ('from', 'to', 'cc', 'recipients', 'references', 'in_reply_to', 'bounced_email', 'bounced_message', 'bounced_msg_id', 'bounced_partner'):
                post_params.pop(x, None)
            new_msg = False
            if thread._name == 'mail.thread':  # message with parent_id not linked to record
                new_msg = thread.message_notify(**post_params)
            else:
                # parsing should find an author independently of user running mail gateway, and ensure it is not odoobot
                partner_from_found = message_dict.get('author_id') and message_dict['author_id'] != self.env[
                    'ir.model.data']._xmlid_to_res_id('base.partner_root')
                thread = thread.with_context(mail_create_nosubscribe=not partner_from_found)
                new_msg = thread.message_post(**post_params)

            if new_msg and original_partner_ids:
                # postponed after message_post, because this is an external message and we don't want to create
                # duplicate emails due to notifications
                new_msg.write({'partner_ids': original_partner_ids})
        return thread_id

    def _get_value_from_regex_condition(self, regex_condition, email_body):
        """
        Extracts the value from an email body that matches the given regular expression condition.
        """
        if regex_condition and email_body:
            search_pattern = fr"{regex_condition}"
            match = re.search(search_pattern, email_body)
            if match:
                return match.group(1)
            return None

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """
        This method extends the functionality by allowing a custom parser value in the context.
        If 'custom_parser_value' is present and not empty, it is used to extract data.
        The extracted data is then used to execute a server action associated with the alias_id.

        In the server action, retrieve values from the context with the key 'model_name', which
        represents the model name and the corresponding ID of the created record.
        Example Usage:{'res_partner': 56}
        """
        message_new = super().message_new(msg_dict, custom_values)
        context = dict(self._context) or {}
        
        if 'custom_parser_value' in context and context.get('custom_parser_value'):
            alias_id = context.get('alias_id')
            action_server = alias_id.mail_parser_server_action_id
            if action_server:
                model_name = message_new._name.replace('.', '_')
                data = {
                    'active_model': message_new._name,
                    'active_id': message_new.id,
                    model_name: message_new.id,
                }
                action_server.sudo().with_context(data).run()
        return message_new

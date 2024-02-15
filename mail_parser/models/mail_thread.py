import re
from itertools import groupby
from odoo import _, api, models
from odoo.tools import html2plaintext


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _mail_parser_custom(self, model, thread_id, custom_values, user_id, alias_id, message):
        """
        Prepare custom value from email
        """
        if alias_id and alias_id.mail_parser_ids:
            mail_parser_by_model = {}
            for models_id, grouped_lines in groupby(alias_id.mail_parser_ids, key=lambda l: l.models_id.id):
                mail_parser_by_model[models_id] = self.env['mail.parser'].concat(*grouped_lines)
            if mail_parser_by_model:
                linked_dict = {}
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

                    if model_id:
                        custom_model_id = False
                        model_id_rec = self.env['ir.model'].browse(model_id)
                        if model_id_rec and model_vals:
                            model_obj = self.env[model_id_rec.model]
                            domain = self._prepared_domain_from_dict(domain_vals)
                            if domain:
                                custom_model_id = model_obj.search(domain, limit=1)
                            if not custom_model_id:
                                custom_model_id = model_obj.create(model_vals)
                            model_name = model_id_rec.model.replace('.', '_')
                            linked_dict.update({
                                model_name: custom_model_id.id,
                                'alias_id': alias_id
                            })
                return linked_dict

    def _prepared_domain_from_dict(self, model_vals):
        """
        Prepared domain from dictionary
        """
        domain = []
        for key, value in model_vals.items():
            domain.append((key,'=', value))
        return domain

    @api.model
    def _message_route_process(self, message, message_dict, routes):
        """
        Method overwrite from
        URL: https://github.com/odoo/odoo/blob/56666f8f7858fcbcce466d2240135b35509d2d96/addons/mail/models/mail_thread.py#L1224
        """
        self = self.with_context(attachments_mime_plainxml=True) # import XML attachments as text
        # postpone setting message_dict.partner_ids after message_post, to avoid double notifications
        original_partner_ids = message_dict.pop('partner_ids', [])
        thread_id = False
        custom_parser_value = {}

        for model, thread_id, custom_values, user_id, alias in routes or ():
            subtype_id = False
            related_user = self.env['res.users'].browse(user_id)
            if alias.mail_parser_ids:
                custom_parser_value = self._mail_parser_custom(model, thread_id, custom_values, user_id, alias, message_dict.get('body'))
            Model = self.env[model].with_context(custom_parser_value=custom_parser_value, mail_create_nosubscribe=True, mail_create_nolog=True)
            if not (thread_id and hasattr(Model, 'message_update') or hasattr(Model, 'message_new')):
                raise ValueError(
                    "Undeliverable mail with Message-Id %s, model %s does not accept incoming emails" %
                    (message_dict['message_id'], model)
                )

            # disabled subscriptions during message_new/update to avoid having the system user running the
            # email gateway become a follower of all inbound messages
            ModelCtx = Model.with_user(related_user).sudo()
            if thread_id and hasattr(ModelCtx, 'message_update'):
                thread = ModelCtx.browse(thread_id)
                thread.message_update(message_dict)
            else:
                # if a new thread is created, parent is irrelevant
                message_dict.pop('parent_id', None)
                # Report failure/record success of message creation except if alias is not defined (fallback model case)
                try:
                    thread = ModelCtx.message_new(message_dict, custom_values)
                except Exception:
                    if alias:
                        with self.pool.cursor() as new_cr:
                            self.with_env(self.env(cr=new_cr)).env['mail.alias'].browse(alias.id
                            )._alias_bounce_incoming_email(message, message_dict, set_invalid=True)
                    raise
                else:
                    if alias and alias.alias_status != 'valid':
                        alias.alias_status = 'valid'
                thread_id = thread.id
                subtype_id = thread._creation_subtype().id

            # switch to odoobot for all incoming message creation
            # to have a priviledged archived user so real_author_id is correctly computed
            thread_root = thread.with_user(self.env.ref('base.user_root'))
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
            for x in ('from', 'to', 'cc', 'recipients', 'references', 'in_reply_to', 'is_bounce', 'bounced_email', 'bounced_message', 'bounced_msg_ids', 'bounced_partner'):
                post_params.pop(x, None)
            new_msg = False
            if thread_root._name == 'mail.thread':  # message with parent_id not linked to record
                new_msg = thread_root.message_notify(**post_params)
            else:
                # parsing should find an author independently of user running mail gateway, and ensure it is not odoobot
                partner_from_found = message_dict.get('author_id') and message_dict['author_id'] != self.env['ir.model.data']._xmlid_to_res_id('base.partner_root')
                thread_root = thread_root.with_context(from_alias=True, mail_create_nosubscribe=not partner_from_found)
                new_msg = thread_root.message_post(**post_params)

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
        data = {}
        context = dict(self._context) or {}
        if 'custom_parser_value' in context and context.get('custom_parser_value'):
            data = {'active_model': message_new._name, 'active_id': message_new.id}
            if isinstance(context.get('custom_parser_value'), dict):
                data.update(context.get('custom_parser_value').copy())
            action_server = data.get('alias_id').mail_parser_server_action_id
            if action_server:
                action_server.sudo().with_context(data).run()
        return message_new

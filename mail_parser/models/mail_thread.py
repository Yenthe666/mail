# -*- coding: utf-8 -*-
import re
from itertools import groupby
from odoo import api, models
from odoo.tools import html2plaintext


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _mail_parser_custom(self, model, thread_id, custom_values, user_id, alias_id, message_dict):
        """
        Prepare custom value from email
        """
        message = message_dict.get('body')
        if not (alias_id and alias_id.mail_parser_ids):
            return custom_values, message_dict, {}

        mail_parser_by_model = {}
        for models_id, grouped_lines in groupby(
            alias_id.mail_parser_ids, key=lambda l: l.models_id.id
        ):
            mail_parser_by_model[models_id] = self.env['mail.parser'].concat(*grouped_lines)

        if not mail_parser_by_model:
            return custom_values, message_dict, {}

        model_vals = {}
        domain_vals = {}

        for model_id, parser_id in mail_parser_by_model.items():
            for parser in parser_id:
                email_body = str(message)
                tags_to_replace = ["<b>", "</b>"]
                for tag in tags_to_replace:
                    email_body = email_body.replace(tag, "")
                email_body = html2plaintext(email_body)
                regex_match_value = self._get_value_from_regex_condition(
                    parser.regex_condition, email_body
                )
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
                        continue

        if model_vals.get('email', False) and message_dict.get('email_from', False):
            message_dict.update({'email_from': model_vals.get('email', False)})

        custom_values.update(model_vals)
        return custom_values, message_dict, domain_vals

    def _prepared_domain_from_dict(self, domain_vals):
        """
        Prepared domain from dictionary
        """
        domain = []
        for key, value in domain_vals.items():
            domain.append((key, '=', value))
        return domain

    @api.model
    def _message_route_process(self, message, message_dict, routes):
        self = self.with_context(attachments_mime_plainxml=True)
        original_partner_ids = message_dict.pop('partner_ids', [])
        thread_id = False

        for model, thread_id, custom_values, user_id, alias in routes or ():
            subtype_id = False
            related_user = self.env['res.users'].browse(user_id)
            Model = self.env[model].with_context(
                mail_create_nosubscribe=True, mail_create_nolog=True
            )
            if not (thread_id and hasattr(Model, 'message_update') or hasattr(Model, 'message_new')):
                raise ValueError(
                    "Undeliverable mail with Message-Id %s, model %s does not accept incoming emails" %
                    (message_dict['message_id'], model)
                )

            if alias and alias.mail_parser_ids:
                custom_values, message_dict, domain_vals = self._mail_parser_custom(
                    model,
                    thread_id,
                    custom_values,
                    user_id,
                    alias,
                    message_dict,
                )
                domain = self._prepared_domain_from_dict(domain_vals)
                existing_record_id = Model.search(domain, limit=1)
                Model = Model.with_context(
                    custom_parser_value=custom_values,
                    alias_id=alias,
                    existing_record_id=existing_record_id,
                )
                if existing_record_id:
                    thread_id = existing_record_id.id

            ModelCtx = Model.with_user(related_user).sudo()
            if thread_id and hasattr(ModelCtx, 'message_update'):
                thread = ModelCtx.browse(thread_id)
                thread.message_update(message_dict)
            else:
                message_dict.pop('parent_id', None)
                try:
                    thread = ModelCtx.message_new(message_dict, custom_values)
                except Exception:
                    if alias:
                        with self.pool.cursor() as new_cr:
                            self.with_env(self.env(cr=new_cr)).env['mail.alias'].browse(
                                alias.id
                            )._alias_bounce_incoming_email(
                                message, message_dict, set_invalid=True
                            )
                    raise
                else:
                    if alias and alias.alias_status != 'valid':
                        alias.alias_status = 'valid'
                thread_id = thread.id
                subtype_id = thread._creation_subtype().id

            thread_root = thread.with_user(self.env.ref('base.user_root'))

            parent_message = False
            if message_dict.get('parent_id'):
                parent_message = self.env['mail.message'].sudo().browse(
                    message_dict['parent_id']
                )
            partner_ids = []
            if not subtype_id:
                if message_dict.get('is_internal'):
                    subtype_id = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note')
                    if parent_message and parent_message.author_id:
                        partner_ids = [parent_message.author_id.id]
                else:
                    subtype_id = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_comment')

            post_params = dict(subtype_id=subtype_id, partner_ids=partner_ids, **message_dict)
            for x in ('from', 'to', 'cc', 'recipients', 'references', 'in_reply_to',
                      'x_odoo_message_id', 'is_bounce', 'bounced_email', 'bounced_message',
                      'bounced_msg_ids', 'bounced_partner'):
                post_params.pop(x, None)

            new_msg = False
            if thread_root._name == 'mail.thread':
                new_msg = thread_root.message_notify(**post_params)
            else:
                partner_from_found = (
                    message_dict.get('author_id') and
                    message_dict['author_id'] != self.env['ir.model.data']._xmlid_to_res_id(
                        'base.partner_root'
                    )
                )
                thread_root = thread_root.with_context(
                    from_alias=True,
                    mail_create_nosubscribe=not partner_from_found,
                )
                new_msg = thread_root.message_post(**post_params)

            if new_msg and original_partner_ids:
                new_msg.write({'partner_ids': original_partner_ids})

        return thread_id

    def _get_value_from_regex_condition(self, regex_condition, email_body):
        """
        Extracts the value from an email body that matches the given
        regular expression condition.
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
        Extends message_new to execute the server action configured on the alias
        after a new record is created from an incoming email.

        In the server action, retrieve values from the context with the key
        'model_name' (model name) and 'active_id' (ID of the created record).
        Example: {'res_partner': 56}
        """
        message_new = super().message_new(msg_dict, custom_values)
        context = dict(self._context) or {}

        if context.get('custom_parser_value'):
            alias_id = context.get('alias_id')
            if alias_id:
                action_server = alias_id.mail_parser_server_action_id
                if action_server:
                    action_server.sudo().with_context(
                        model_name=self._name,
                        active_id=message_new.id,
                    ).run()
        return message_new
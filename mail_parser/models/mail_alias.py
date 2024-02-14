import re

from odoo import models, fields, api, _
from odoo.tools import html2plaintext


class MailAlias(models.Model):
    _inherit="mail.alias"

    mail_parser_ids = fields.One2many(
        "mail.parser",
        "mail_alias_id",
        string="Mail Parser rules"
    )

    mail_parser_server_action_id = fields.Many2one(
        "ir.actions.server",
        "Mail parser server action",
        help="The server action that should be executed automatically the moment an email is created from an alias.",
        domain="[('model_id','=', alias_model_id)]"
    )

    test_mail_body = fields.Html(
        string="Mail Body"
    )

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

    def test_mail_parser_rule(self):
        table_tag_open = "<table class='table'><tbody>"
        table_data_string = ''
        table_tag_close = "</tbody></table>"
        action = self.env['ir.actions.act_window']._for_xml_id("mail_parser.parser_message_wizard_action")
        for alias in self:
            model_vals = self._prepare_mail_parser_data(alias_id=alias)
            for key, value in model_vals.items():
                table_data_string += f"<tr><td><b>{key}</b></td><td>{value}</td></tr>"
        final_data_string = f"{table_tag_open}{table_data_string}{table_tag_close}"
        action['context'] = {
            'default_parser_message': final_data_string
         }
        return action

    def _prepare_mail_parser_data(self, alias_id):
        model_vals = {}
        if alias_id and alias_id.mail_parser_ids:
            email_body = str(alias_id.test_mail_body)
            tags_to_replace = ["<b>", "</b>"]
            for tag in tags_to_replace:
                email_body = email_body.replace(tag, "")
            email_body=html2plaintext(email_body)
            for parser_id in alias_id.mail_parser_ids:
                regex_match_value =  self._get_value_from_regex_condition(parser_id.regex_condition, email_body)
                if regex_match_value:
                    model_vals[parser_id.name] = regex_match_value
                else:
                    if parser_id.default_value:
                        model_vals[parser_id.name] = parser_id.default_value
                    else:
                         model_vals[parser_id.name] = ''
        return model_vals

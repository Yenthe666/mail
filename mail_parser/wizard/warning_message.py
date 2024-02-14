from odoo import models, fields, api, _


class ParserMessage(models.TransientModel):
    _name = 'parser.message'
    _description = 'Parser Message'

    parser_message = fields.Html(
        string='Message',
        required=True
    )

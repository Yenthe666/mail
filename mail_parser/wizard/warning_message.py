# -*- coding: utf-8 -*-
from odoo import models, fields


class ParserMessage(models.TransientModel):
    _name = 'parser.message'
    _description = 'Parser Message'

    parser_message = fields.Html(
        string='Message',
        required=True,
    )
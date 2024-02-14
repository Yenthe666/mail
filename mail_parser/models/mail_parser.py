from odoo import models, fields, api, _


class MailParser(models.Model):
    _name="mail.parser"
    _description ="Mail Parser"

    name = fields.Char(
        string="Name"
    )

    regex_condition = fields.Char(
        string="Regex condition"
    )

    field_id = fields.Many2one(
        "ir.model.fields",
        string="Fields"
    )

    models_id = fields.Many2one(
        "ir.model",  # model to which this rule is linked
        string="Model"
    )

    default_value = fields.Char(
        string="Default Value"
    )

    mail_alias_id = fields.Many2one(
        "mail.alias",
        string="Alias"
    )

    should_be_unique = fields.Boolean(
        string="Should be Unique",
    )

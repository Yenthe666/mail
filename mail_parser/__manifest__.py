# -*- coding: utf-8 -*-

{
    "name": "Mail Parser",
    "version": "16.0.1.0.6",
    "summary": """
        Automatically read/parse emails from aliases and convert data
        """,
    "description": """
        Automatically read/parse emails from aliases and convert data
    """,
    "author": "Mainframe Monkey",
    "website": "https://www.mainframemonkey.com",
    "category": "Productivity/Discuss",
    "depends": [
        "base",
        "mail"
        ],
    "data": [
        "security/ir.model.access.csv",
        "views/mail_alias_views.xml",
        "views/mail_parser_views.xml",
        "wizard/warning_message_views.xml"
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}

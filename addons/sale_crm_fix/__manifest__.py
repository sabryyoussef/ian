# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Sale CRM Fix',
    'version': '1.0',
    'category': 'Hidden',
    'description': """
Fix for sale_crm module compatibility with Odoo 18
    """,
    'depends': ['sale_crm'],
    'data': [
        'views/partner_views_fix.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
}

# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Sale CRM Patch',
    'version': '1.0',
    'category': 'Hidden',
    'description': """
Patch for sale_crm module to fix Odoo 18 compatibility
    """,
    'depends': ['sale_crm'],
    'data': [
        'views/partner_views_patch.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
}

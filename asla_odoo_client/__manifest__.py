{
    'name': 'ASLA Client Agent',
    'version': '18.0.1.2.0',
    'summary': 'AI agent inside your own Odoo: answers, support tickets and module requests',
    'description': """
ASLA Client Agent
=================

A free, open-source agent that runs **inside your own Odoo 18**:

* **AslaBot in Discuss** answers questions about Odoo, grounded in your own configuration.
* **Support tickets** are raised in your Odoo and answered there.
* **Administration with a plan**: anything that changes data is planned, dry-run and
  approved by a person. Users, permissions and accounting entries are never changed
  automatically, and that list lives in your database.

Offline mode keeps everything on your machine. Online mode sends your question and the
structure of the models involved -- field names and types, never the rows -- to the ASLA Hub.

Licence: LGPL-3. Documentation: https://odoo.asla.mn/client
""",
    'author': 'ITAUCO',
    'maintainer': 'ITAUCO',
    'website': 'https://odoo.asla.mn/client',
    'support': 'devops@itauco.mn',
    'category': 'Productivity/Artificial Intelligence',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'portal', 'website'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/asla_bot_groups.xml',
        'security/ir.model.access.csv',
        'data/asla_bot_data.xml',
        'data/aslabot_data.xml',
        'data/ir_sequence_data.xml',
        'views/asla_project_views.xml',
        'views/bot_operation_views.xml',
        'views/bot_ticket_views.xml',
        'views/portal_templates.xml',
        'views/res_config_settings_views.xml',
        'views/z_menu.xml',
        'views/z_menu_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'application': True,
    'installable': True,
}

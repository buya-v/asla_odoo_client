"""Rename this module's xmlids away from the retired `asla_studio` naming.

Renaming an xmlid in XML without moving `ir_model_data` first makes the loader
treat the record as new: the old row is orphaned and a *second* menu, action or
bot partner appears in the customer's database. The bot partner is the one that
matters -- a duplicate there means Discuss shows two AslaBots and the code's
`env.ref` picks whichever it finds.

This runs before the data files load, so the existing records keep their ids.
"""
import logging

_logger = logging.getLogger(__name__)

RENAMES = {
    'partner_asla_studio_bot': 'partner_aslabot',
    'user_asla_studio_bot': 'user_aslabot',
    'menu_asla_studio_root': 'menu_aslabot_root',
    'menu_asla_studio_generate': 'menu_aslabot_projects',
    'menu_asla_studio_config': 'menu_aslabot_config',
    'menu_asla_studio_settings': 'menu_aslabot_settings',
    'action_asla_studio_project': 'action_aslabot_project',
    'action_asla_studio_config_settings': 'action_aslabot_config_settings',
}


def migrate(cr, version):
    renamed = 0
    for old, new in RENAMES.items():
        # Only if the new name is free: a re-run must not collide.
        cr.execute("""
            UPDATE ir_model_data SET name = %s
             WHERE module = 'asla_odoo_client' AND name = %s
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data
                    WHERE module = 'asla_odoo_client' AND name = %s)
        """, (new, old, new))
        renamed += cr.rowcount
    _logger.info('asla_odoo_client: %s xmlids renamed off the asla_studio naming', renamed)

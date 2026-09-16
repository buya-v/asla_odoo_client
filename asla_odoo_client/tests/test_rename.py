from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRenamedRecords(TransactionCase):
    """The xmlids moved off the retired `asla_studio` naming in 18.0.1.2.0.

    A stale xmlid has already made this bot mute once (see chat_assistant.py), so
    the names the code looks up are pinned by a test rather than by memory.
    """

    def test_the_bot_partner_and_user_resolve(self):
        partner = self.env.ref('asla_odoo_client.partner_aslabot')
        user = self.env.ref('asla_odoo_client.user_aslabot')
        self.assertTrue(partner.name)
        self.assertEqual(user.partner_id, partner)

    def test_the_code_looks_up_the_name_that_exists(self):
        from odoo.addons.asla_odoo_client.models import chat_assistant, res_users
        for module in (chat_assistant, res_users):
            self.assertTrue(self.env.ref(module.BOT_XMLID, raise_if_not_found=False),
                            module.BOT_XMLID)

    def test_the_menus_and_actions_resolve(self):
        for xmlid in ('menu_aslabot_root', 'menu_aslabot_projects', 'menu_aslabot_config',
                      'menu_aslabot_settings', 'action_aslabot_project',
                      'action_aslabot_config_settings'):
            self.assertTrue(self.env.ref('asla_odoo_client.%s' % xmlid, raise_if_not_found=False), xmlid)

    def test_there_is_exactly_one_bot_partner(self):
        # A botched rename leaves the old ir_model_data row behind and creates a
        # second partner; Discuss then shows two AslaBots.
        partner = self.env.ref('asla_odoo_client.partner_aslabot')
        same_name = self.env['res.partner'].with_context(active_test=False).search_count(
            [('name', '=', partner.name)])
        self.assertEqual(same_name, 1)


@tagged('post_install', '-at_install')
class TestRetiredSettingsStillRead(TransactionCase):
    """The settings keys were renamed; an instance written by an older version
    must keep working, because the operation mode decides whether anything
    leaves the customer's network."""

    def setUp(self):
        super().setUp()
        self.params = self.env['ir.config_parameter'].sudo()
        for key in ('asla_client.operation_mode', 'asla_studio.operation_mode'):
            self.params.search([('key', '=', key)]).unlink()

    def test_the_new_key_is_used(self):
        self.params.set_param('asla_client.operation_mode', 'online')
        self.assertEqual(self.env['asla_client.ai'].mode(), 'online')

    def test_a_retired_key_is_still_honoured(self):
        self.params.set_param('asla_studio.operation_mode', 'online')
        self.assertEqual(self.env['asla_client.ai'].mode(), 'online')

    def test_the_new_key_wins_over_the_retired_one(self):
        self.params.set_param('asla_studio.operation_mode', 'online')
        self.params.set_param('asla_client.operation_mode', 'export_rfp')
        self.assertEqual(self.env['asla_client.ai'].mode(), 'export_rfp')

    def test_the_default_is_offline_when_nothing_is_set(self):
        self.assertEqual(self.env['asla_client.ai'].mode(), 'export_rfp')

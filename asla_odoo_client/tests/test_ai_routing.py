from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

_POST = 'odoo.addons.asla_odoo_client.models.ai.AslaAi._post'


@tagged('post_install', '-at_install')
class TestAiRouting(TransactionCase):
    """Offline must stay offline, and an ungrounded answer must say so."""

    def setUp(self):
        super().setUp()
        self.ai = self.env['asla_client.ai']
        self.params = self.env['ir.config_parameter'].sudo()

    def _mode(self, mode):
        self.params.set_param('asla_client.operation_mode', mode)

    def test_offline_asks_the_local_service_and_is_grounded(self):
        self._mode('export_rfp')
        with patch(_POST, return_value={'answer': 'hi', 'sources': ['a']}) as post:
            result = self.ai.answer('How do I add a field?')
        self.assertEqual(result['via'], 'asla_odoo_ai')
        self.assertTrue(result['grounded'])
        self.assertFalse(result['degraded'])
        self.assertIn('localhost:8080', post.call_args[0][0])  # the local service, not the hub

    def test_without_the_local_service_the_answer_says_it_is_not_grounded(self):
        self._mode('export_rfp')
        calls = []

        def fake_post(this, url, payload):
            calls.append(url)
            if '8080' in url:
                raise OSError('connection refused')
            return {'message': {'content': 'a plain answer'}}

        with patch(_POST, fake_post):
            result = self.ai.answer('How do I add a field?')
        self.assertEqual(result['via'], 'ollama')
        self.assertFalse(result['grounded'])
        self.assertTrue(result['degraded'])
        self.assertIn('notice', result)
        self.assertEqual(len(calls), 2)  # tried the grounded service first

    def test_when_nothing_answers_the_user_gets_a_message_not_an_exception(self):
        self._mode('export_rfp')
        with patch(_POST, side_effect=OSError('nothing there')):
            result = self.ai.answer('How do I add a field?')
        self.assertEqual(result['via'], 'none')
        self.assertTrue(result['degraded'])
        self.assertTrue(result['answer'])

    def test_online_without_pairing_tells_the_user_to_pair(self):
        self._mode('online')
        self.env['asla_client.hub'].search([]).unlink()
        with patch(_POST, side_effect=AssertionError('nothing may leave in this case')):
            result = self.ai.answer('How do I add a field?')
        self.assertEqual(result['via'], 'none')
        self.assertTrue(result['degraded'])
        self.assertTrue(result['answer'])
        # The wording is translated, so it is checked in English explicitly:
        # asserting on the default language fails on a Mongolian install.
        english = self.ai.with_context(lang='en_US').answer('How do I add a field?')
        self.assertIn('not paired', english['answer'])

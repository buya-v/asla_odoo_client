import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestRpcAuth(HttpCase):
    """/asla/bot/rpc has no Odoo session and dispatches as superuser, so the
    token is the only thing between a stranger and the customer's database."""

    def _call(self, payload, token=None, raw=None):
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer %s' % token
        body = raw if raw is not None else json.dumps(payload)
        return self.url_open('/asla/bot/rpc', data=body, headers=headers)

    def _pair(self, hub_token='hub-token-for-tests'):
        return self.env['asla_client.hub'].create({
            'name': 'Test hub', 'state': 'paired', 'client_id': 'CLIENT-1',
            'hub_rpc_url': 'https://hub.example/asla/hub/rpc',  # required
            'hub_token': hub_token, 'bot_token': 'bot-token',
        })

    def test_an_unpaired_instance_answers_nothing(self):
        self.env['asla_client.hub'].search([]).unlink()
        body = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'ticket.set_state'}, token='x').json()
        self.assertEqual(body['error']['code'], -32001)

    def test_a_missing_or_wrong_token_is_refused(self):
        self._pair()
        for token in (None, '', 'wrong', 'hub-token-for-test'):  # the last is one character short
            body = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'ticket.set_state'}, token=token).json()
            self.assertEqual(body['error']['code'], -32001, token)

    def test_the_right_token_gets_past_authentication(self):
        self._pair()
        body = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'no.such.method'},
                          token='hub-token-for-tests').json()
        # Past auth: it fails on the method, not on the token.
        self.assertNotEqual(body['error']['code'], -32001)

    def test_a_mismatched_client_id_is_refused(self):
        self._pair()
        body = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'ticket.set_state',
                           'params': {'client_id': 'SOMEONE-ELSE'}},
                          token='hub-token-for-tests').json()
        self.assertEqual(body['error']['code'], -32002)

    def test_an_old_protocol_is_refused(self):
        self._pair()
        body = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'ticket.set_state',
                           'params': {'protocol_version': '0.9'}},
                          token='hub-token-for-tests').json()
        self.assertEqual(body['error']['code'], -32003)

    def test_a_huge_body_is_refused_before_it_is_parsed(self):
        self._pair()
        response = self._call(None, token='hub-token-for-tests', raw='{"a": "%s"}' % ('x' * (1024 * 1024 + 10)))
        self.assertEqual(response.json()['error']['message'], 'Request too large')

    def test_junk_is_not_a_traceback(self):
        self._pair()
        for raw in ('not json at all', '[]', '"a string"'):
            body = self._call(None, token='hub-token-for-tests', raw=raw).json()
            self.assertEqual(body['error']['message'], 'Invalid JSON', raw)

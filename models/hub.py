import logging
import uuid

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1.0"
_TIMEOUT = 30


class AslaBotHub(models.Model):
    """Connection to the AslaBot hub — the bot side of the intake channel.

    Holds the paired credentials and provides the outbound JSON-RPC client used
    to submit tickets, push config, report operation results, and -- in online
    mode -- reach the hub's Gemma4 for chat. See hub-bot-protocol.md.

    Ported from the legacy asla_bot addon. controllers/main.py already searched
    for `asla.bot.hub`, a model that did not exist after the namespace
    migration, so the inbound endpoint could never authenticate a request.
    """

    _name = 'asla_client.hub'
    _description = 'AslaBot Hub Connection'
    _inherit = ['mail.thread']

    name = fields.Char(string='Name', default='AslaBot Hub', required=True)
    hub_rpc_url = fields.Char(
        string='Hub RPC URL', required=True,
        help='e.g. https://odoo.asla.mn/asla/hub/rpc')
    client_id = fields.Char(
        string='Client ID', help='Tenant key assigned by the hub at pairing.')
    protocol_version = fields.Char(default=PROTOCOL_VERSION, readonly=True)
    state = fields.Selection([
        ('unpaired', 'Unpaired'),
        ('paired', 'Paired'),
    ], default='unpaired', string='Status', tracking=True)

    enrollment_code = fields.Char(
        string='Enrollment Code',
        help='One-time code generated in the hub to pair this bot.')
    # Credentials restricted to admins; encrypt at rest before production (FR-8.1).
    bot_token = fields.Char(string='Bot Token', groups='asla_odoo_client.group_asla_bot_admin')
    hub_token = fields.Char(string='Hub Token', groups='asla_odoo_client.group_asla_bot_admin')

    last_heartbeat = fields.Datetime(string='Last Heartbeat', readonly=True)

    # --- outbound JSON-RPC (intake channel) ------------------------------------

    def _envelope(self):
        """Common protocol envelope for every call (see spec §3)."""
        self.ensure_one()
        return {
            'protocol_version': PROTOCOL_VERSION,
            'client_id': self.client_id or '',
            'correlation_id': uuid.uuid4().hex,
            'ts': fields.Datetime.now().isoformat() + 'Z',
        }

    def _intake(self, method, params, token=None):
        """POST a JSON-RPC request to the hub. Returns the result or raises.

        Never logs the bearer token.
        """
        self.ensure_one()
        payload = {
            'jsonrpc': '2.0',
            'id': uuid.uuid4().int % 1_000_000,
            'method': method,
            'params': {**self._envelope(), **params},
        }
        headers = {'Content-Type': 'application/json'}
        bearer = token or self.bot_token
        if bearer:
            headers['Authorization'] = f'Bearer {bearer}'
        try:
            resp = requests.post(self.hub_rpc_url, json=payload,
                                 headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()
            body = resp.json()
        except requests.RequestException as exc:
            _logger.warning('hub call %s failed: %s', method, exc)
            raise UserError(_('Hub unreachable: %s') % exc) from exc
        if body.get('error'):
            err = body['error']
            _logger.warning('hub returned error for %s: %s', method, err.get('code'))
            raise UserError(_('Hub error %(code)s: %(msg)s') % {
                'code': err.get('code'), 'msg': err.get('message')})
        return body.get('result', {})

    # --- actions ---------------------------------------------------------------

    def action_pair(self):
        """session.pair (spec §4): exchange the enrollment code for tokens."""
        self.ensure_one()
        if not self.enrollment_code:
            raise UserError(_('Enter the enrollment code generated in the hub.'))
        result = self._intake('session.pair', {
            'enrollment_code': self.enrollment_code,
            'bot': {'version': '1.0.0',
                    'odoo_version': self._odoo_version(),
                    'endpoint': self._bot_endpoint()},
        }, token=None)
        self.write({
            'client_id': result.get('client_id'),
            'bot_token': result.get('bot_token'),
            'hub_token': result.get('hub_token'),
            'enrollment_code': False,
            'state': 'paired',
        })
        self.message_post(body=_('Paired with hub as client %s.') % self.client_id)

    def action_push_config(self):
        """client.push_config (spec §8): send a live introspection snapshot."""
        self.ensure_one()
        self._intake('client.push_config', {'config': self._introspect()})
        self.message_post(body=_('Pushed configuration snapshot to hub.'))

    def action_heartbeat(self):
        """heartbeat (spec §5/§10)."""
        self.ensure_one()
        self._intake('heartbeat', {
            'bot_version': '1.0.0', 'health': 'healthy',
            'queue_depth': 0})
        self.write({'last_heartbeat': fields.Datetime.now()})

    def report_operation(self, operation_ref, status, result=None, error=None,
                         duration=0.0):
        """operation.report_result (spec §5) — called by asla_client.mcp.operation."""
        self.ensure_one()
        return self._intake('operation.report_result', {
            'operation_ref': operation_ref, 'status': status,
            'result': result, 'error': error,
            'executed_by': self.env.user.login, 'duration': duration})

    def chat_answer(self, query, role='BA', lang='mn'):
        """chat.answer — a grounded Gemma4 answer from the hub.

        Online mode reaches the hub's copy of asla_odoo_ai rather than a local
        one. Free at the hub, rate-limited rather than metered.
        """
        self.ensure_one()
        return self._intake('chat.answer', {
            'query': query, 'role': role, 'lang': lang})

    def submit_ticket(self, vals):
        """ticket.submit (spec §5) — called by asla_client.ticket on create."""
        self.ensure_one()
        return self._intake('ticket.submit', vals)

    # --- helpers ---------------------------------------------------------------

    def _introspect(self):
        """Gather this instance's Odoo config for client.push_config."""
        Module = self.env['ir.module.module'].sudo()  # sudo(): read-only module list
        installed = Module.search([('state', '=', 'installed')]).mapped('name')
        return {
            'odoo_version': self._odoo_version(),
            'edition': 'Community',
            'modules_installed': installed,
            'modules_absent': [],
            'ui_language': self.env.user.lang or 'en_US',
        }

    def _odoo_version(self):
        return self.env['ir.module.module'].sudo().get_module_info('base').get(
            'version', '18.0').split('.')[0] + '.0'

    def _bot_endpoint(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return f"{base}/asla/bot/rpc"

    @staticmethod
    def _get(env):
        """Return the (single) configured hub connection, or an empty recordset."""
        return env['asla_client.hub'].sudo().search([('state', '=', 'paired')], limit=1)

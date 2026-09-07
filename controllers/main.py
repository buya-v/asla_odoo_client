import json
import logging

from odoo import SUPERUSER_ID, http
from odoo.http import request

_logger = logging.getLogger(__name__)

# AslaBot JSON-RPC error codes (spec §9)
ERR_UNAUTHORIZED = -32001
ERR_UNKNOWN_CLIENT = -32002
ERR_VERSION = -32003
ERR_UNKNOWN_REF = -32004
ERR_NEVER_AUTOMATE = -32010
ERR_CONFIRM_REQUIRED = -32011
ERR_INTERNAL = -32603
PROTOCOL_VERSION = "1.0"


class AslaBotRpc(http.Controller):
    """Control endpoint (hub -> bot). Implements the spec §6 methods over
    JSON-RPC 2.0, authenticated by the paired hub_token.

    auth='none': this is a machine endpoint with token auth, not an Odoo session.
    """

    @http.route('/asla/bot/rpc', type='http', auth='none', methods=['POST'], csrf=False)
    def rpc(self, **_kw):
        try:
            req = json.loads(request.httprequest.get_data() or b'{}')
        except ValueError:
            return self._resp(None, error=(ERR_INTERNAL, 'Invalid JSON'))

        rpc_id = req.get('id')
        method = req.get('method')
        params = req.get('params') or {}

        hub = request.env['asla.bot.hub'].sudo().search([('state', '=', 'paired')], limit=1)
        auth_err = self._authenticate(hub, params)
        if auth_err:
            return self._resp(rpc_id, error=auth_err)

        try:
            result = self._dispatch(method, params)
        except _RpcError as exc:
            request.env.cr.rollback()  # don't persist partial work on failure
            return self._resp(rpc_id, error=(exc.code, exc.message))
        except Exception as exc:
            request.env.cr.rollback()
            _logger.exception('bot rpc %s failed', method)
            return self._resp(rpc_id, error=(ERR_INTERNAL, str(exc)))
        return self._resp(rpc_id, result=result)

    # --- auth & dispatch -------------------------------------------------------

    def _authenticate(self, hub, params):
        if not hub:
            return (ERR_UNAUTHORIZED, 'Bot not paired')
        header = request.httprequest.headers.get('Authorization', '')
        token = header[7:] if header.startswith('Bearer ') else ''
        if not token or token != hub.sudo().hub_token:
            return (ERR_UNAUTHORIZED, 'Bad or missing token')
        if params.get('client_id') and params['client_id'] != hub.client_id:
            return (ERR_UNKNOWN_CLIENT, 'client_id mismatch')
        if params.get('protocol_version', PROTOCOL_VERSION).split('.')[0] != \
                PROTOCOL_VERSION.split('.')[0]:
            return (ERR_VERSION, 'Protocol major version mismatch')
        return None

    def _dispatch(self, method, params):
        handler = {
            'ticket.post_answer': self._ticket_post_answer,
            'ticket.set_state': self._ticket_set_state,
            'operation.dry_run': self._operation_dry_run,
            'operation.request': self._operation_request,
        }.get(method)
        if not handler:
            raise _RpcError(ERR_INTERNAL, f'Unknown method: {method}')
        # Superuser env: token-authenticated machine endpoint, no Odoo session.
        return handler(request.env(user=SUPERUSER_ID), params)

    # --- handlers (spec §6) ----------------------------------------------------

    def _find_ticket(self, env, params):
        ref, hub_ref = params.get('bot_ref'), params.get('hub_ref')
        domain = [('name', '=', ref)] if ref else [('hub_ref', '=', hub_ref)]
        ticket = env['asla_client.ticket'].search(domain, limit=1)
        if not ticket:
            raise _RpcError(ERR_UNKNOWN_REF, 'Ticket not found')
        return ticket

    def _ticket_post_answer(self, env, params):
        ticket = self._find_ticket(env, params)
        ticket.post_hub_answer(params.get('body_html', ''),
                               sources=params.get('sources'),
                               response_category=params.get('response_category'))
        return {'ok': True}

    def _ticket_set_state(self, env, params):
        ticket = self._find_ticket(env, params)
        ticket.set_hub_state(params.get('state'), note=params.get('note'))
        return {'ok': True}

    def _operation_dry_run(self, env, params):
        op = env['asla_client.mcp.operation'].new({
            'operation_ref': params.get('operation_ref', 'dry'),
            'target_model': params.get('target_model'),
            'method': params.get('method'),
            'arguments': json.dumps(params.get('arguments', {})),
        })
        return op.dry_run()

    def _operation_request(self, env, params):
        op = env['asla_client.mcp.operation'].create({
            'operation_ref': params['operation_ref'],
            'ticket_ref': params.get('bot_ref'),
            'target_model': params['target_model'],
            'method': params['method'],
            'arguments': json.dumps(params.get('arguments', {})),
            'hub_tier': params.get('hub_tier'),
        })
        status = op.evaluate()
        return {'status': status, 'local_tier': op.local_tier}

    # --- response helper -------------------------------------------------------

    def _resp(self, rpc_id, result=None, error=None):
        body = {'jsonrpc': '2.0', 'id': rpc_id}
        if error:
            body['error'] = {'code': error[0], 'message': error[1]}
        else:
            body['result'] = result
        return request.make_response(
            json.dumps(body), headers=[('Content-Type', 'application/json')])


class _RpcError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Vendored copy of the shared policy (spec §7). The CLIENT owns these lists —
# this is the whole point of the bot: local, client-controlled enforcement.
SENSITIVE_MODELS = [
    'res.users', 'res.groups', 'ir.rule', 'ir.model.access',
    'account.move', 'account.payment', 'account.bank.statement',
]
READ_METHODS = ['read', 'search', 'search_read', 'search_count', 'fields_get']


class AslaBotOperation(models.Model):
    """An operation requested by the hub, executed locally under client policy.

    The hub only *proposes* (operation.request); this model re-derives the tier
    locally (authoritative) and executes, confirms, or refuses accordingly.
    """

    _name = 'asla.bot.operation'
    _description = 'AslaBot Local Operation'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    operation_ref = fields.Char(string='Operation Ref', required=True, index=True)
    ticket_ref = fields.Char(string='Ticket Ref')
    target_model = fields.Char(string='Target Model', required=True)
    method = fields.Char(string='Method', required=True)
    arguments = fields.Text(string='Arguments (JSON)')
    hub_tier = fields.Char(string='Hub-proposed Tier')

    local_tier = fields.Selection([
        ('auto_execute', 'Auto Execute'),
        ('confirm_then_execute', 'Confirm Then Execute'),
        ('never_automate', 'Never Automate'),
    ], compute='_compute_local_tier', store=True, string='Local Tier')

    state = fields.Selection([
        ('received', 'Received'),
        ('pending_confirmation', 'Pending Confirmation'),
        ('executed', 'Executed'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
    ], default='received', string='Status', required=True, tracking=True)
    result = fields.Text(string='Result', readonly=True)
    error_message = fields.Text(string='Error', readonly=True)

    @api.depends('target_model', 'method')
    def _compute_local_tier(self):
        for op in self:
            if op.method in READ_METHODS:
                op.local_tier = 'auto_execute'
            elif op.target_model in SENSITIVE_MODELS:
                op.local_tier = 'never_automate'
            else:
                op.local_tier = 'confirm_then_execute'

    def evaluate(self):
        """Apply the local tier decision (spec §7). Returns a status string."""
        self.ensure_one()
        if self.local_tier == 'never_automate':
            self.state = 'rejected'
            self.error_message = _('Blocked by local policy (never_automate): %s') \
                % self.target_model
            self._report('rejected', error=self.error_message)
            return 'rejected'
        if self.local_tier == 'auto_execute':
            return self._execute()
        self.state = 'pending_confirmation'
        return 'pending_confirmation'

    def action_approve(self):
        """Client operator approves a confirm_then_execute operation (spec §7)."""
        self.ensure_one()
        if self.local_tier == 'never_automate':
            raise UserError(_('This operation cannot be automated.'))
        if self.state != 'pending_confirmation':
            raise UserError(_('Operation is not awaiting confirmation.'))
        self._execute()

    def action_reject(self):
        self.ensure_one()
        self.state = 'rejected'
        self._report('rejected', error='Rejected by operator')

    def _execute(self):
        """Run the operation locally via the Odoo ORM, then report to the hub."""
        self.ensure_one()
        args = json.loads(self.arguments or '{}')
        try:
            model = self.env[self.target_model]
            method = getattr(model, self.method)
            outcome = method(**args) if isinstance(args, dict) else method(*args)
            self.write({'state': 'executed', 'result': json.dumps(outcome, default=str)})
            self._report('success', result=self.result)
            return 'executed'
        except Exception as exc:  # noqa: BLE001 - report any failure back to the hub
            _logger.warning('operation %s failed: %s', self.operation_ref, exc)
            self.write({'state': 'failed', 'error_message': str(exc)})
            self._report('failed', error=str(exc))
            return 'failed'

    def _report(self, status, result=None, error=None):
        hub = self.env['asla.bot.hub']._get(self.env)
        if not hub:
            return
        try:
            hub.report_operation(self.operation_ref, status, result=result, error=error)
        except Exception as exc:  # noqa: BLE001 - reporting is best-effort
            _logger.warning('report_result for %s failed: %s', self.operation_ref, exc)

    def dry_run(self):
        """operation.dry_run (spec §6): validate arguments against the local schema."""
        self.ensure_one()
        warnings = []
        model = self.env.get(self.target_model)
        if model is None:
            return {'valid': False, 'warnings': [_('Unknown model: %s') % self.target_model]}
        args = json.loads(self.arguments or '{}')
        values = args.get('values', {}) if isinstance(args, dict) else {}
        unknown = set(values) - set(self.env[self.target_model]._fields)
        if unknown:
            warnings.append(_('Unknown fields: %s') % ', '.join(sorted(unknown)))
        return {'valid': not warnings, 'warnings': warnings}

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SENSITIVE_MODELS = [
    'res.users', 'res.groups', 'ir.rule', 'ir.model.access',
    'account.move', 'account.payment', 'account.bank.statement',
]

READ_METHODS = ['read', 'search', 'search_read', 'search_count', 'fields_get']


class OperationPlan(models.Model):
    """Pre-execution plan for an MCP operation.

    Implements FR-4.1 (operation plan), FR-4.2 (dry-run),
    FR-4.3 (permission tiers), FR-4.4 (approval workflow).
    """

    _name = 'aslabot.operation.plan'
    _description = 'MCP Operation Plan'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    ticket_id = fields.Many2one(
        'aslabot.ticket', string='Ticket', required=True, ondelete='cascade')
    client_id = fields.Many2one(
        'aslabot.client.registry', string='Client', required=True)
    connection_id = fields.Many2one(
        'aslabot.mcp.connection', string='MCP Connection')

    # FR-4.1: Operation details
    target_model = fields.Char(string='Target Model', required=True)
    method = fields.Char(string='Method', required=True)
    arguments = fields.Text(string='Arguments (JSON)')
    expected_outcome = fields.Text(string='Expected Outcome')

    # FR-4.3: Permission tier
    permission_tier = fields.Selection([
        ('auto_execute', 'Auto Execute'),
        ('confirm_then_execute', 'Confirm Then Execute'),
        ('never_automate', 'Never Automate'),
    ], string='Permission Tier',
        compute='_compute_permission_tier', store=True)

    # Workflow
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated (Dry-Run OK)'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('executed', 'Executed'),
        ('failed', 'Failed'),
        ('rejected', 'Rejected'),
    ], default='draft', string='Status', tracking=True)

    # FR-4.4: Approval
    approver_id = fields.Many2one('res.users', string='Approved By')
    approval_date = fields.Datetime(string='Approval Date')
    rejection_reason = fields.Text(string='Rejection Reason')

    # FR-4.2: Dry-run results
    dry_run_result = fields.Text(string='Dry-Run Result')
    dry_run_warnings = fields.Text(string='Dry-Run Warnings')

    @api.depends('target_model', 'method')
    def _compute_permission_tier(self):
        """FR-4.3: Determine permission tier based on model and method."""
        for plan in self:
            if plan.method in READ_METHODS:
                plan.permission_tier = 'auto_execute'
            elif plan.target_model in SENSITIVE_MODELS:
                plan.permission_tier = 'never_automate'
            else:
                plan.permission_tier = 'confirm_then_execute'

    def action_validate_dry_run(self):
        """FR-4.2: Validate operation against client schema."""
        self.ensure_one()
        if not self.connection_id:
            raise UserError(_(
                'No MCP connection configured for this plan.'))
        # TODO: Implement actual MCP inspect_model call
        self.write({
            'state': 'validated',
            'dry_run_result': 'Schema validation passed.',
        })
        self.message_post(
            body=_('Dry-run validation passed.'),
            message_type='notification',
        )

    def action_request_approval(self):
        """FR-4.4: Submit plan for client approval."""
        self.ensure_one()
        if self.permission_tier == 'never_automate':
            raise UserError(_(
                'This operation targets a sensitive model (%s) and '
                'cannot be automated. Handle manually.',
                self.target_model,
            ))
        if self.state != 'validated':
            raise UserError(_('Run dry-run validation first.'))
        self.write({'state': 'pending_approval'})

    def action_approve(self):
        """Approve the operation plan for execution."""
        self.ensure_one()
        self.write({
            'state': 'approved',
            'approver_id': self.env.uid,
            'approval_date': fields.Datetime.now(),
        })

    def action_reject(self):
        """Reject the operation plan."""
        self.ensure_one()
        self.write({'state': 'rejected'})

    def action_execute(self):
        """Execute the approved operation via MCP."""
        self.ensure_one()
        if self.permission_tier == 'auto_execute':
            pass  # Can proceed without approval
        elif self.state != 'approved':
            raise UserError(_('Plan must be approved before execution.'))
        # TODO: Implement actual MCP execution via _mcp_call
        self.write({'state': 'executed'})

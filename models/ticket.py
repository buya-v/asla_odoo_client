import logging

from markupsafe import Markup, escape

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AslaBotTicket(models.Model):
    """A support ticket raised by a client user, relayed to the AslaBot hub.

    This is the client-facing intake surface (spec §5). The hub's grounded
    answer comes back via the control endpoint and is posted to this chatter.
    """

    _name = 'asla.bot.ticket'
    _description = 'AslaBot Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'))
    hub_ref = fields.Char(string='Hub Reference', readonly=True, copy=False)
    subject = fields.Char(string='Subject', required=True)
    description = fields.Html(string='Description', required=True)
    category = fields.Selection([
        ('admin', 'Administration'),
        ('support', 'Support'),
        ('customization', 'Customization'),
    ], default='support', required=True, string='Category')
    priority = fields.Selection([
        ('0', 'Low'), ('1', 'Normal'), ('2', 'High'), ('3', 'Urgent'),
    ], default='1', string='Priority')
    lang = fields.Char(string='Language', default=lambda self: self.env.user.lang or 'mn')
    reporter_id = fields.Many2one(
        'res.partner', string='Reporter',
        default=lambda self: self.env.user.partner_id)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('triaged', 'Triaged'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('failed', 'Failed'),
        ('escalated', 'Escalated'),
    ], default='draft', string='Status', required=True, tracking=True)
    response_category = fields.Selection([
        ('automated', 'Automated'),
        ('needs_review', 'Needs Review'),
        ('requires_consultation', 'Requires Consultation'),
    ], string='Response Category', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'asla.bot.ticket') or _('New')
        tickets = super().create(vals_list)
        for ticket in tickets:
            ticket._submit_to_hub()
        return tickets

    def _submit_to_hub(self):
        """Relay the ticket to the hub (best-effort; queue on failure)."""
        self.ensure_one()
        hub = self.env['asla.bot.hub']._get(self.env)
        if not hub:
            self.message_post(body=_('No paired hub — ticket stored locally only.'))
            return
        try:
            result = hub.submit_ticket({
                'bot_ref': self.name,
                'subject': self.subject,
                'body': self.description or '',
                'category': self.category,
                'priority': self.priority,
                'lang': self.lang,
                'reporter': {'name': self.reporter_id.name,
                             'email': self.reporter_id.email or ''},
            })
            self.write({'hub_ref': result.get('hub_ref'),
                        'state': result.get('state', 'submitted')})
        except Exception as exc:  # noqa: BLE001 - submission is best-effort
            _logger.warning('ticket %s submit failed: %s', self.name, exc)
            self.message_post(body=_('Hub submission pending (will retry): %s') % exc)

    # --- called by the control endpoint (hub -> bot) ---------------------------

    def post_hub_answer(self, body_html, sources=None, response_category=None):
        """ticket.post_answer (spec §6): post the grounded answer to the chatter."""
        self.ensure_one()
        body = Markup(body_html or '')
        if sources:
            # Markup % escapes both operands; the sources list is plain text.
            body = body + Markup('<p><i>%s %s</i></p>') % (_('Sources:'), ', '.join(sources))
        if response_category:
            self.response_category = response_category
        self.message_post(body=body, message_type='comment')

    def set_hub_state(self, state, note=None):
        """ticket.set_state (spec §6)."""
        self.ensure_one()
        if state in dict(self._fields['state'].selection):
            self.state = state
        if note:
            self.message_post(body=escape(note))

    def action_submit(self):
        """Manual resubmit for tickets that failed to reach the hub."""
        for ticket in self:
            ticket._submit_to_hub()

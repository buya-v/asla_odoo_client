# -*- coding: utf-8 -*-
"""AslaBot replies in Discuss.

Two bugs made the bot mute. It looked up
`asla_studio.partner_asla_studio_bot`, but the data moved to this module, so
the xmlid is `asla_odoo_client.partner_asla_studio_bot` -- and with
`raise_if_not_found=False` the lookup returned None and the hook returned
early, silently, with nothing in the log. The reply worker had the same stale
ref. Both are fixed, and the module prefix is now derived rather than spelled
out, so a future rename fails loudly instead of going quiet.

The AI call itself moved to `asla_client.ai`, which routes offline/online and
is shared with the RFP flow.
"""
import html
import json
import logging
import re
import threading

from markupsafe import Markup

from odoo import api, models

_logger = logging.getLogger(__name__)

BOT_XMLID = 'asla_odoo_client.partner_asla_studio_bot'
HISTORY_LIMIT = 10


def _strip_html(value):
    return re.sub(r'<[^>]+>', '', value or '').strip()


def _to_html(text):
    safe = html.escape(text or '')
    safe = safe.replace('\n', '<br/>')
    safe = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe)
    safe = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" target="_blank">\1</a>', safe)
    return Markup('<p>%s</p>' % safe)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _message_post_after_hook(self, message, msg_vals):
        res = super()._message_post_after_hook(message, msg_vals)
        try:
            bot = self.env.ref(BOT_XMLID, raise_if_not_found=False)
            if not bot:
                _logger.warning('AslaBot partner %s missing; not replying', BOT_XMLID)
                return res
            if self.channel_type != 'chat':
                return res
            if bot.id not in self.channel_partner_ids.ids:
                return res
            if msg_vals.get('author_id') == bot.id:
                return res

            text = _strip_html(msg_vals.get('body'))
            if not text:
                return res

            member = self.channel_member_ids.filtered(lambda m: m.partner_id.id == bot.id)
            if member:
                member._notify_typing(is_typing=True)
            self._asla_reply_async(self.id, text)
        except Exception:
            _logger.exception('AslaBot reply hook failed')
        return res

    # ------------------------------------------------------------------

    def _asla_reply_async(self, channel_id, text):
        """Answer on a worker thread; a chat reply must not block the request."""
        db_name = self.env.cr.dbname

        def _work():
            import odoo
            registry = odoo.registry(db_name)
            try:
                with registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                    channel = env['discuss.channel'].browse(channel_id)
                    bot = env.ref(BOT_XMLID, raise_if_not_found=False)
                    if not channel.exists() or not bot:
                        return
                    history, transcript = channel._asla_history(bot)
                    result = env['asla_client.ai'].answer(text, role='BA', history=history)
                    channel._asla_post_reply(bot, result, transcript)
            except Exception:
                _logger.exception('AslaBot reply failed')

        self.env.cr.postcommit.add(
            lambda: threading.Thread(target=_work, daemon=True).start())

    def _asla_history(self, bot):
        """Recent turns as (chat messages, plain transcript)."""
        self.ensure_one()
        messages = self.env['mail.message'].search([
            ('res_id', '=', self.id),
            ('model', '=', 'discuss.channel'),
            ('message_type', '=', 'comment'),
        ], order='id desc', limit=HISTORY_LIMIT)
        turns, lines = [], []
        for m in reversed(messages):
            body = _strip_html(m.body)
            if not body:
                continue
            is_bot = m.author_id.id == bot.id
            turns.append({'role': 'assistant' if is_bot else 'user', 'content': body})
            lines.append('%s: %s' % ('AslaBot' if is_bot else 'User', body))
        return turns, '\n'.join(lines)

    def _asla_post_reply(self, bot, result, transcript):
        """Post the answer, creating the RFP project when the bot says [READY]."""
        self.ensure_one()
        answer = result.get('answer', '')

        if '[READY]' in answer:
            answer = answer.replace('[READY]', '').strip()
            answer = answer or "Шаардлага тодорхой боллоо. Төслийг үүсгэж байна…"
            project = self.env['asla_client.rfp.project'].create({
                'name': 'App request from Discuss channel %s' % self.id,
                'prompt': transcript,
            })
            project.action_export_rfp()
            base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            # The model name here was stale (asla.app.project), so the success
            # link 404'd at the moment the flow finally worked.
            answer += "\n\n**[%s](%s/odoo/action-base.action_ui_view#id=%s&model=asla_client.rfp.project&view_type=form)**" % (
                "Таны төсөл ба RFP бэлэн боллоо!", base, project.id)

        if result.get('notice'):
            answer += "\n\n_%s_" % result['notice']

        self.with_context(mail_create_nosubscribe=True).message_post(
            body=_to_html(answer),
            author_id=bot.id,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            silent=True,
        )

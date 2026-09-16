# -*- coding: utf-8 -*-
"""Put AslaBot in the user's Discuss direct messages.

This is why AslaBot was invisible: the partner and user records existed and
were searchable, but nothing ever created the conversation, so there was
nothing to see in Discuss. The legacy asla_studio module did this and was never
ported.

Follows Odoo 18's own mail_bot pattern rather than the legacy one. The legacy
module overrode `_init_messaging(store)`, which still exists and still fires;
but OdooBot itself uses `_on_webclient_bootstrap()`, which runs once on
webclient load rather than on every messaging init.
"""
import logging

from markupsafe import Markup

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

BOT_XMLID = 'asla_odoo_client.partner_asla_studio_bot'


class ResUsers(models.Model):
    _inherit = 'res.users'

    asla_bot_state = fields.Selection([
        ('not_initialized', 'Not initialized'),
        ('initialized', 'Initialized'),
        ('disabled', 'Disabled'),
    ], string='AslaBot Status', readonly=True, default='not_initialized')

    @property
    def SELF_READABLE_FIELDS(self):
        # Without this the user cannot read their own state and the check below
        # raises during bootstrap.
        return super().SELF_READABLE_FIELDS + ['asla_bot_state']

    def _on_webclient_bootstrap(self):
        super()._on_webclient_bootstrap()
        if self._is_internal() and self.asla_bot_state in (False, 'not_initialized'):
            try:
                self._init_asla_bot()
            except Exception:
                # A greeting is not worth breaking someone's login over.
                _logger.exception('AslaBot initialisation failed for user %s', self.id)

    def _init_asla_bot(self):
        """Open the DM with AslaBot and say hello. Once per user."""
        self.ensure_one()
        bot_partner = self.env.ref(BOT_XMLID, raise_if_not_found=False)
        if not bot_partner:
            _logger.warning('AslaBot partner %s not found; skipping', BOT_XMLID)
            return

        channel = self.env['discuss.channel'].channel_get(
            [bot_partner.id, self.partner_id.id])
        channel.sudo().message_post(
            body=self._asla_bot_welcome(),
            author_id=bot_partner.id,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            # silent: this is a greeting, not something to email people about.
            silent=True,
        )
        self.sudo().asla_bot_state = 'initialized'
        return channel

    def _asla_bot_welcome(self):
        """Bilingual: the bot answers in Mongolian, but the operator may not
        read it, and an unreadable first message looks like a broken bot."""
        return Markup(
            "<p><b>Сайн байна уу! Би <b>AslaBot</b> байна.</b></p>"
            "<p>Би таны Odoo системийн бизнес шинжээч. Танд ямар програм "
            "хэрэгтэй байгааг надад хэлээрэй — би шаардлагыг тодруулж, "
            "аппликейшныг тань үүсгэнэ.</p>"
            "<p class=\"text-muted\"><i>I am AslaBot, your Odoo business "
            "analyst. Tell me what you want to build and I will gather the "
            "requirements and generate the app. You can write in Mongolian or "
            "English.</i></p>"
        )

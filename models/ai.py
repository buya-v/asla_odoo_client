# -*- coding: utf-8 -*-
"""One AI client for AslaBot, routed by operation mode.

Gemma4 is never inside Odoo -- it is 15 GB of weights served by Ollama, which
asla_odoo_ai wraps with retrieval. The same service runs in both modes; only
the URL differs:

    offline   this machine   Odoo -> asla_odoo_ai -> Ollama gemma4:e2b
    online    hub machine    Odoo -> hub RPC -> asla_odoo_ai -> Ollama gemma4:e4b

Online is not merely the same model rented. The hub's corpus and accumulated
per-client context are things an air-gapped instance cannot replicate.

If asla_odoo_ai is unreachable offline but Ollama is, this falls back to
talking to Ollama directly AND SAYS SO. A degraded answer that looks identical
to a grounded one is worse than an error, because nobody can tell you why the
answers got worse.

Replaces two near-identical ~70-line copies of this logic that had drifted
apart in chat_assistant.py and rfp_generator.py.
"""
import json
import logging
import urllib.error
import urllib.request

from odoo import _, api, models

_logger = logging.getLogger(__name__)

P_AI_URL = 'asla_client.ai_url'
P_OLLAMA_URL = 'asla_client.ollama_url'
P_OLLAMA_MODEL = 'asla_client.ollama_model'
P_MODE = 'asla_studio.operation_mode'

DEFAULT_AI_URL = 'http://localhost:8080'
# Not host.docker.internal: that resolves on Docker Desktop and nowhere else,
# so the previous hardcoded value could not reach Ollama on a Linux server.
DEFAULT_OLLAMA_URL = 'http://localhost:11434'
DEFAULT_OLLAMA_MODEL = 'gemma4:e2b'
TIMEOUT = 600

BA_SYSTEM = (
    "You are an Odoo Business Analyst. The user wants to build or change an "
    "Odoo application. Ask clarifying questions about their requirements. "
    "Reply EXCLUSIVELY in Mongolian (Монгол хэл), Cyrillic script. "
    "When you understand the entities well enough to build a data model, "
    "reply with the exact token [READY]. Do not emit [READY] before then."
)


class AslaAi(models.AbstractModel):
    _name = 'asla_client.ai'
    _description = 'AslaBot AI Client'

    @api.model
    def _param(self, key, default):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    @api.model
    def mode(self):
        return self._param(P_MODE, 'export_rfp')

    @api.model
    def answer(self, query, role='BA', lang='mn', history=None):
        """Return {'answer', 'sources', 'grounded', 'degraded', 'via'}.

        Never raises: a chat bot that throws leaves the user staring at silence.
        Failures come back as a readable message with degraded=True.
        """
        if self.mode() == 'online':
            return self._answer_online(query, role, lang)
        return self._answer_offline(query, role, lang, history)

    # ------------------------------------------------------------------

    @api.model
    def _answer_online(self, query, role, lang):
        hub = self.env['asla_client.hub']._get(self.env)
        if not hub:
            return self._fail(_(
                "Online mode is selected but this instance is not paired with "
                "the ASLA Hub. Pair it in Settings, or switch to offline mode."))
        try:
            result = hub.chat_answer(query, role=role, lang=lang)
            return {'answer': result.get('answer', ''),
                    'sources': result.get('sources', []),
                    'grounded': True, 'degraded': False, 'via': 'hub'}
        except Exception as exc:
            _logger.warning('hub chat failed: %s', exc)
            return self._fail(_("The ASLA Hub is not reachable: %s", exc))

    @api.model
    def _answer_offline(self, query, role, lang, history):
        url = self._param(P_AI_URL, DEFAULT_AI_URL).rstrip('/')
        try:
            body = self._post('%s/api/answer' % url,
                              {'role': role, 'query': query,
                               'client_id': None, 'lang': lang})
            return {'answer': body.get('answer', ''),
                    'sources': body.get('sources', []),
                    'grounded': True, 'degraded': False, 'via': 'asla_odoo_ai'}
        except Exception as exc:
            _logger.info('asla_odoo_ai unreachable (%s); falling back to Ollama', exc)

        # Fallback: the model without the retrieval around it.
        try:
            messages = [{'role': 'system', 'content': BA_SYSTEM}]
            messages += list(history or [])
            messages.append({'role': 'user', 'content': query})
            body = self._post(
                '%s/api/chat' % self._param(P_OLLAMA_URL, DEFAULT_OLLAMA_URL).rstrip('/'),
                {'model': self._param(P_OLLAMA_MODEL, DEFAULT_OLLAMA_MODEL),
                 'messages': messages, 'stream': False})
            return {'answer': (body.get('message') or {}).get('content', ''),
                    'sources': [], 'grounded': False, 'degraded': True,
                    'via': 'ollama',
                    'notice': _("Answered without grounding: the asla_odoo_ai "
                                "service is not reachable, so no corpus was consulted.")}
        except Exception as exc:
            _logger.error('Ollama unreachable: %s', exc)
            return self._fail(_(
                "Neither asla_odoo_ai (%(ai)s) nor Ollama (%(ol)s) is reachable.",
                ai=url, ol=self._param(P_OLLAMA_URL, DEFAULT_OLLAMA_URL)))

    # ------------------------------------------------------------------

    @api.model
    def _post(self, url, payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))

    @api.model
    def _fail(self, message):
        return {'answer': message, 'sources': [], 'grounded': False,
                'degraded': True, 'via': 'none'}

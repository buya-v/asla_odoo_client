from odoo import api, models
import logging
import re
import threading
import json
import urllib.request
from markupsafe import Markup

_logger = logging.getLogger(__name__)

class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _message_post_after_hook(self, message, msg_vals):
        res = super()._message_post_after_hook(message, msg_vals)
        try:
            bot_partner = self.env.ref('asla_studio.partner_asla_studio_bot', raise_if_not_found=False)
            if not bot_partner:
                return res
                
            if bot_partner.id not in self.channel_partner_ids.ids:
                return res
            if msg_vals.get('author_id') == bot_partner.id:
                return res
                
            if self.channel_type != 'chat':
                return res

            body = msg_vals.get('body', '')
            clean_text = re.sub(r'<[^>]+>', '', body).strip()
            
            if clean_text:
                bot_member = self.channel_member_ids.filtered(lambda m: m.partner_id.id == bot_partner.id)
                if bot_member:
                    bot_member._notify_typing(is_typing=True)
                
                self._send_to_gemma_async(self.id, clean_text, msg_vals.get('author_id'))
                
        except Exception as e:
            _logger.exception("Gemma Bot Error: %s", e)
        return res

    def _send_to_gemma_async(self, channel_id, text, author_id):
        db_name = self.env.cr.dbname
        
        def _do_ai_call():
            import odoo
            registry = odoo.registry(db_name)
            
            # Step 1: Fetch history
            conversation = ""
            bot_partner_id = None
            try:
                with registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                    channel = env['discuss.channel'].browse(channel_id)
                    bot_partner = env.ref('asla_studio.partner_asla_studio_bot', raise_if_not_found=False)
                    if not channel.exists() or not bot_partner:
                        return
                    bot_partner_id = bot_partner.id
                    
                    messages = env['mail.message'].search([
                        ('res_id', '=', channel.id),
                        ('model', '=', 'discuss.channel'),
                        ('message_type', '=', 'comment')
                    ], order='id desc', limit=10)
                    
                    system_prompt = (
                        "You are an Odoo Business Analyst. The user wants to build an Odoo app. "
                        "Ask clarifying questions about their database requirements. "
                        "CRITICAL INSTRUCTION: You MUST communicate with the user EXCLUSIVELY in the Mongolian language (Монгол хэл). Use Cyrillic script. Do NOT use Kyrgyz, Kazakh, Russian, English or Chinese. "
                        "When you have enough information to build a basic data model, you MUST reply with the exact word [READY]. "
                        "Do not output [READY] until you understand the basic entities needed."
                    )
                    history = []
                    api_messages = [{"role": "system", "content": system_prompt}]
                    for m in reversed(messages):
                        sender = "Gemma" if m.author_id.id == bot_partner.id else "User"
                        role = "assistant" if m.author_id.id == bot_partner.id else "user"
                        m_clean = re.sub(r'<[^>]+>', '', m.body).strip()
                        if m_clean:
                            history.append(f"{sender}: {m_clean}")
                            api_messages.append({"role": role, "content": m_clean})
                    conversation = "\n".join(history)
            except Exception as e:
                _logger.exception("Failed to fetch history")
                return
                
            payload = json.dumps({
                "model": "gemma4:e2b",
                "messages": api_messages,
                "stream": False
            }).encode('utf-8')
            
            try:
                req = urllib.request.Request("http://host.docker.internal:11434/api/chat", data=payload, headers={'Content-Type': 'application/json'})
                # Increased timeout to 300s (5 mins) for heavy Qwen model
                with urllib.request.urlopen(req, timeout=300) as resp:
                    result = json.loads(resp.read().decode())
                    ai_reply = result.get('message', {}).get('content', '')
            except Exception as e:
                _logger.error("Ollama connection error: %s", e)
                ai_reply = "I am having trouble connecting to Ollama. The Qwen 14B model might be loading or the request timed out."
                
            # Step 3: Save Reply
            try:
                with registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                    channel = env['discuss.channel'].browse(channel_id)
                    
                    if "[READY]" in ai_reply:
                        ai_reply = ai_reply.replace("[READY]", "").strip()
                        if not ai_reply:
                            ai_reply = "I have all the requirements I need! I am generating your app now..."
                            
                        project = env['asla_client.rfp.project'].create({
                            'name': f"App Request from Channel {channel.id}",
                            'prompt': conversation,
                        })
                        project.action_export_rfp()
                        
                        base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
                        project_url = f"{base_url}/web#id={project.id}&model=asla.app.project&view_type=form"
                        ai_reply += f"\n\n**[Your Project & RFP are ready!]({project_url})**"

                    import html
                    safe_html = html.escape(ai_reply)
                    safe_html = safe_html.replace('\n', '<br/>')
                    safe_html = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe_html)
                    safe_html = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" target="_blank">\1</a>', safe_html)
                    
                    channel.with_context(mail_create_nosubscribe=True).message_post(
                        body=Markup(f"<p>{safe_html}</p>"),
                        author_id=bot_partner_id,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                        silent=True,
                    )
            except Exception as e:
                _logger.exception("Failed to save AI reply")
                
        def _spawn_thread():
            thread = threading.Thread(target=_do_ai_call, daemon=True)
            thread.start()
            
        self.env.cr.postcommit.add(_spawn_thread)

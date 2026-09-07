import json
import base64
import urllib.request
import tempfile
import os
import threading
from odoo import models, fields, api, exceptions, _
from odoo.tools import convert_xml_import

class AslaAppProject(models.Model):
    _name = 'asla.app.project'
    _description = 'ASLA App Generation Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Project Name", required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft (Gathering Requirements)'),
        ('ready', 'RFP Ready for Download'),
        ('done', 'App Installed')
    ], string="Status", default='draft', tracking=True)
    
    # We get operation_mode from settings default, but let users see it.
    operation_mode = fields.Selection([
        ('online', 'Online API (Auto-Install)'),
        ('export_rfp', 'Offline Mode: Export RFP (ZIP)'),
        ('import_app', 'Offline Mode: Import Generated App (ZIP)')
    ], string="Operation Mode", required=True, default=lambda self: self.env['ir.config_parameter'].sudo().get_param('asla_studio.operation_mode', 'export_rfp'))

    rfp_file = fields.Binary(string="Download RFP ZIP", readonly=True, tracking=True)
    rfp_file_name = fields.Char(string="RFP File Name")
    
    app_upload_file = fields.Binary(string="Upload Generated App ZIP")
    app_upload_filename = fields.Char(string="Upload File Name")
    
    prompt = fields.Text(string="Aggregated Prompt", help="Hidden field capturing the entire chat history for the RFP")

    def _get_schema_context(self):
        models = self.env['ir.model'].search([('transient', '=', False)])
        schema_data = []
        for model in models:
            fields_data = self.env['ir.model.fields'].search([('model_id', '=', model.id)])
            field_names = [f.name for f in fields_data]
            schema_data.append(f"Model: {model.model}, Fields: {', '.join(field_names)}")
        return "\n".join(schema_data[:20]) # Limit for local LLM

    def action_export_rfp(self):
        """Called when Gemma decides she is READY, or user clicks a button"""
        for rec in self:
            schema_info = rec._get_schema_context()
            rfp_data = json.dumps({
                "prompt": rec.prompt or rec.name,
                "schema": schema_info
            }, ensure_ascii=False, indent=4)
            
            import zipfile
            fd, path = tempfile.mkstemp(suffix='.zip')
            with zipfile.ZipFile(path, 'w') as zf:
                zf.writestr('rfp.json', rfp_data.encode('utf-8'))
                
            with open(path, 'rb') as f:
                zip_b64 = base64.b64encode(f.read())
                
            os.remove(path)
            
            rec.write({
                'rfp_file': zip_b64,
                'rfp_file_name': 'asla_rfp.zip',
                'state': 'ready'
            })
            
            rec.message_post(body="The RFP ZIP file has been generated and is ready for download in the attachments/fields above!")

    def action_import_app(self):
        """Imports the uploaded APP.zip"""
        for rec in self:
            if not rec.app_upload_file:
                raise exceptions.UserError(_('Please upload the App ZIP file.'))
                
            zip_bytes = base64.b64decode(rec.app_upload_file)
            fd, path = tempfile.mkstemp(suffix='.zip')
            with os.fdopen(fd, 'wb') as f:
                f.write(zip_bytes)
                
            xml_content = None
            with zipfile.ZipFile(path, 'r') as zf:
                if 'app.xml' in zf.namelist():
                    xml_content = zf.read('app.xml').decode('utf-8')
            os.remove(path)
            
            if not xml_content:
                raise exceptions.UserError(_('Invalid App ZIP: app.xml not found.'))
                
            try:
                fd, path = tempfile.mkstemp(suffix='.xml')
                with os.fdopen(fd, 'w') as f:
                    f.write(xml_content)
                with open(path, 'rb') as f:
                    convert_xml_import(self.env, 'asla_generated', f, idref={}, mode='init', noupdate=False)
                os.remove(path)
                
                rec.write({'state': 'done'})
                rec.message_post(body="Success! The AI generated app has been hot-reloaded into your Odoo database.")
            except Exception as e:
                raise exceptions.UserError(_(f'Failed to import generated XML into database: {str(e)}'))

    def action_undo(self):
        """Rollback the most recently installed AI App by purging its records."""
        data_records = self.env['ir.model.data'].search([('module', '=', 'asla_generated')])
        if not data_records:
            raise exceptions.UserError(_('Nothing to undo. No AI-generated records found.'))
            
        deleted_count = 0
        for data in data_records:
            try:
                record = self.env[data.model].browse(data.res_id)
                if record.exists():
                    record.unlink()
                data.unlink()
                deleted_count += 1
            except Exception as e:
                continue
                
        self.write({'state': 'draft'})
        self.message_post(body=f"Rollback Complete! Successfully removed {deleted_count} AI-generated records from your database.")

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        """Intercept messages to pass to Gemma"""
        message = super(AslaAppProject, self).message_post(**kwargs)
        
        # Avoid recursive loops if the message is from Odoo system (e.g. no author_id or is Gemma)
        # Assuming the author is a real user. 
        if kwargs.get('author_id') and self.state == 'draft' and kwargs.get('message_type') == 'comment':
            body = kwargs.get('body', '')
            import re
            clean_text = re.sub(r'<[^>]+>', '', body).strip()
            
            if clean_text:
                self._send_to_gemma_async(self.id, clean_text)
                
        return message

    def _send_to_gemma_async(self, project_id, text):
        db_name = self.env.cr.dbname
        
        def _do_ai_call():
            try:
                import odoo
                registry = odoo.registry(db_name)
                with registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                    project = env['asla.app.project'].browse(project_id)
                    
                    if project.exists():
                        # Aggregate prompt
                        current_prompt = project.prompt or project.name
                        updated_prompt = current_prompt + "\nUser: " + text
                        project.prompt = updated_prompt
                        
                        system_prompt = (
                            "You are an Odoo Business Analyst. The user wants to build an Odoo app. "
                            "Ask clarifying questions about their database requirements. "
                            "CRITICAL INSTRUCTION: You MUST communicate with the user EXCLUSIVELY in the Mongolian language (Монгол хэл). Use Cyrillic script. Do NOT use Kyrgyz, Kazakh, Russian, English or Chinese. "
                            "When you have enough information to build a basic data model, you MUST reply with the exact word [READY]. "
                            "Do not output [READY] until you understand the basic entities needed."
                        )
                        
                        api_messages = [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Conversation so far:\n{updated_prompt}"}
                        ]
                        
                        payload = json.dumps({
                            "model": "gemma4:e2b",
                            "messages": api_messages,
                            "stream": False
                        }).encode('utf-8')
                        
                        try:
                            req = urllib.request.Request("http://host.docker.internal:11434/api/chat", data=payload, headers={'Content-Type': 'application/json'})
                            with urllib.request.urlopen(req, timeout=300) as resp:
                                result = json.loads(resp.read().decode())
                                ai_reply = result.get('message', {}).get('content', '')
                        except Exception as e:
                            ai_reply = "I am having trouble connecting to Ollama."
                            
                        # Update prompt with Gemma's reply
                        project.prompt = updated_prompt + f"\nGemma: {ai_reply}"
                        
                        # Post response to chatter
                        project.with_context(mail_create_nosubscribe=True).message_post(
                            body=ai_reply,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                        )
                        
                        # If Gemma is ready, automatically trigger RFP generation!
                        if "[READY]" in ai_reply:
                            project.action_export_rfp()
                            
            except Exception as e:
                pass
                
        thread = threading.Thread(target=_do_ai_call, daemon=True)
        thread.start()

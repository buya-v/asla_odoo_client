import io
import json
import base64
import re
import shutil
import urllib.request
import tempfile
import os
import threading
import zipfile
from odoo import models, fields, api, exceptions, release, _
from odoo.modules.module import get_module_path

class AslaAppProject(models.Model):
    _name = 'asla_client.rfp.project'
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

    request_mode = fields.Selection([
        ('new_module', 'New Module'),
        ('extend_standard', 'Extend a Standard Odoo Module'),
        ('modify_existing', 'Modify an Existing Custom Module'),
    ], string="Request Type", required=True, default='new_module', tracking=True,
        help="Changing an already-installed module is an upgrade, not an install, "
             "and the Hub verifies it differently.")
    target_module = fields.Char(
        string="Module to Modify",
        help="Technical name of the installed module to change. "
             "Required when Request Type is 'Modify an Existing Custom Module'.")
    installed_module = fields.Char(
        string="Installed Module", readonly=True,
        help="Technical name of the module installed from the generated app, "
             "so it can be upgraded or uninstalled later.")
    rfp_preview = fields.Text(
        string="RFP Contents", readonly=True,
        help="Exactly what will be sent to the ASLA Hub. Review before export.")

    @api.constrains('request_mode', 'target_module')
    def _check_target_module(self):
        for rec in self:
            if rec.request_mode != 'modify_existing':
                continue
            if not rec.target_module:
                raise exceptions.ValidationError(
                    _("Select the module to modify."))
            if not rec.env['ir.module.module'].sudo().search_count(
                    [('name', '=', rec.target_module), ('state', '=', 'installed')]):
                raise exceptions.ValidationError(
                    _("Module '%s' is not installed on this database.",
                      rec.target_module))

    # ------------------------------------------------------------------
    # RFP grounding
    #
    # The RFP is the grounding contract for generation, not just a prompt.
    # Generation fails predominantly by inventing field names and xpath anchors
    # that do not exist in the target view, and the only cure is shipping the
    # real ones. Everything here is scoped to the models the request actually
    # touches -- both because unscoped schema is useless to the generator and
    # because the customer should be able to see exactly what leaves the
    # building.
    # ------------------------------------------------------------------

    DOTTED = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b")

    def _detect_targets(self, text):
        """Split dotted tokens in the requirement into known models and view xmlids."""
        models, views = [], []
        for token in dict.fromkeys(self.DOTTED.findall(text or "")):
            module, _, name = token.partition(".")
            xmlid = self.env["ir.model.data"].sudo().search(
                [("module", "=", module), ("name", "=", name),
                 ("model", "=", "ir.ui.view")], limit=1)
            if xmlid:
                views.append(token)
            elif self.env["ir.model"].sudo().search_count([("model", "=", token)]):
                models.append(token)
        return models, views

    def _model_grounding(self, model_name):
        """Field list with types and relation targets -- names alone are useless.

        A generator told only that sale.order has a `partner_id` cannot know it
        is a many2one to res.partner, and will guess.
        """
        rows = self.env["ir.model.fields"].sudo().search_read(
            [("model", "=", model_name)],
            ["name", "ttype", "relation", "field_description", "store"])
        fields_out = [
            {"name": r["name"],
             "type": r["ttype"],
             "relation": r.get("relation") or None,
             "label": r.get("field_description") or "",
             "stored": bool(r.get("store"))}
            for r in rows
        ]
        return {"fields": sorted(fields_out, key=lambda d: d["name"])}

    def _view_grounding(self, xmlid):
        """COMBINED arch, i.e. what an xpath actually resolves against.

        The stored `arch_db` is the module's own contribution only. Every other
        module that inherits the view has already patched it by the time a new
        xpath is applied, and the difference is large -- tens of thousands of
        characters on a form like sale.view_order_form. Grounding on arch_db
        would still produce anchors that do not exist.
        """
        try:
            view = self.env.ref(xmlid)
        except ValueError:
            return {"error": "not found"}
        return {"model": view.model, "type": view.type,
                "arch": view.get_combined_arch()}

    def _installed_modules(self):
        """Decides which sandbox template the Hub builds against."""
        return [{"name": m.name, "version": m.latest_version}
                for m in self.env["ir.module.module"].sudo().search(
                    [("state", "=", "installed")], order="name")]

    def _build_rfp(self):
        """Assemble rfp.json v2."""
        self.ensure_one()
        narrative = self.prompt or self.name
        models, views = self._detect_targets(narrative)

        # When a model is being extended but no view was named, offer its primary
        # form view -- that is where an xpath is usually needed. Framework models
        # (ir.*) are mentioned constantly and are never xpath targets.
        if models and not views:
            for model_name in models:
                if model_name.startswith("ir."):
                    continue
                view = self.env["ir.ui.view"].sudo().search(
                    [("model", "=", model_name), ("type", "=", "form"),
                     ("mode", "=", "primary")], limit=1)
                data = view and self.env["ir.model.data"].sudo().search(
                    [("model", "=", "ir.ui.view"), ("res_id", "=", view.id)], limit=1)
                if data:
                    views.append("%s.%s" % (data.module, data.name))
                    break

        return {
            "rfp_version": 2,
            "generated_at": fields.Datetime.now().isoformat() + "Z",
            "target": {
                "odoo_version": release.version,
                "installed_modules": self._installed_modules(),
            },
            "request": {
                "mode": self.request_mode,
                "target_module": self.target_module or None,
                "summary": self.name,
                "narrative": narrative,
            },
            "grounding": {
                "models": {m: self._model_grounding(m) for m in models},
                "views": {v: self._view_grounding(v) for v in views},
            },
            "existing": self._existing_module() if self.request_mode == "modify_existing" else None,
            "acceptance": {
                "style": "odoo_tests",
                "note": "The Hub generates TransactionCase tests for the stated "
                        "requirement and must run them under --test-enable before "
                        "returning an app.zip.",
            },
        }

    def _existing_module(self):
        """Current source of the module being changed, plus what must survive.

        Without the source the generator rewrites from scratch and silently
        drops whatever it did not think to reproduce; without the record counts
        the Hub cannot prove the upgrade preserved the customer's data.
        """
        self.ensure_one()
        name = self.target_module
        if not name:
            return None
        module = self.env["ir.module.module"].sudo().search([("name", "=", name)], limit=1)
        source = {}
        path = module and get_module_path(name, display_warning=False)
        if path:
            for root, _dirs, files in os.walk(path):
                if any(skip in root for skip in ("__pycache__", "/static", "/.git")):
                    continue
                for fname in files:
                    if not fname.endswith((".py", ".xml", ".csv")):
                        continue
                    full = os.path.join(root, fname)
                    try:
                        source[os.path.relpath(full, path)] = open(
                            full, encoding="utf-8").read()
                    except (OSError, UnicodeDecodeError):
                        continue

        counts = {}
        owned = self.env["ir.model.data"].sudo().search(
            [("module", "=", name), ("model", "=", "ir.model")])
        for data in owned:
            model = self.env["ir.model"].sudo().browse(data.res_id)
            if model.exists() and model.model in self.env:
                counts[model.model] = self.env[model.model].sudo().search_count([])
        return {"module": name,
                "version": module.latest_version if module else None,
                "source": source,
                "record_counts": counts}

    def action_preview_rfp(self):
        """Show the user exactly what would leave the building, before it does."""
        for rec in self:
            rfp = rec._build_rfp()
            rec.rfp_preview = json.dumps(rfp, ensure_ascii=False, indent=2)
        return True

    def action_export_rfp(self):
        """Called when Gemma decides she is READY, or user clicks a button"""
        for rec in self:
            rfp = rec._build_rfp()
            rfp_data = json.dumps(rfp, ensure_ascii=False, indent=4)
            rec.rfp_preview = rfp_data
            
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

    # ------------------------------------------------------------------
    # Importing a generated app
    #
    # The Hub returns a real Odoo module -- a directory with __manifest__.py,
    # Python models, views and tests. The previous implementation expected a
    # single `app.xml` and pushed it through convert_xml_import, which can only
    # create data records; it could never install a module that defines models.
    #
    # Installing this executes code the Hub produced. That trust boundary is
    # inherent to Online Mode, but the archive is still treated as hostile:
    # traversal, absolute paths, symlinks and zip bombs are all rejected before
    # anything touches disk.
    # ------------------------------------------------------------------

    MAX_APP_FILES = 400
    MAX_APP_BYTES = 40 * 1024 * 1024
    ALLOWED_SUFFIXES = ('.py', '.xml', '.csv', '.md', '.txt', '.po', '.pot',
                        '.js', '.scss', '.css', '.svg', '.png', '.jpg', '.gif')

    def _generated_addons_path(self):
        path = self.env['ir.config_parameter'].sudo().get_param(
            'asla_client.generated_addons_path')
        if not path:
            raise exceptions.UserError(_(
                "System parameter 'asla_client.generated_addons_path' is not set. "
                "Point it at a directory that is on this server's Odoo "
                "--addons-path, otherwise a generated module cannot be installed."))
        if not os.path.isdir(path):
            raise exceptions.UserError(
                _("Generated addons path does not exist: %s", path))
        if not os.access(path, os.W_OK):
            raise exceptions.UserError(
                _("Generated addons path is not writable: %s", path))
        return path

    def _safe_extract(self, zip_bytes, dest_root):
        """Validate the archive, then extract it. Returns the module name."""
        try:
            archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile:
            raise exceptions.UserError(_("The uploaded file is not a valid ZIP archive."))

        infos = [i for i in archive.infolist() if not i.is_dir()]
        if not infos:
            raise exceptions.UserError(_("The app archive is empty."))
        if len(infos) > self.MAX_APP_FILES:
            raise exceptions.UserError(
                _("App archive has %s files, which exceeds the limit.", len(infos)))
        if sum(i.file_size for i in infos) > self.MAX_APP_BYTES:
            raise exceptions.UserError(_("App archive is too large once uncompressed."))

        tops = set()
        for info in infos:
            name = info.filename
            if name.startswith('/') or '..' in name.split('/'):
                raise exceptions.UserError(
                    _("Refusing archive: unsafe path %s", name))
            # High bits of external_attr carry the unix mode; 0xA000 is a symlink.
            if (info.external_attr >> 16) & 0xF000 == 0xA000:
                raise exceptions.UserError(
                    _("Refusing archive: it contains a symlink (%s).", name))
            if not name.lower().endswith(self.ALLOWED_SUFFIXES):
                raise exceptions.UserError(
                    _("Refusing archive: unexpected file type %s", name))
            parts = name.split('/')
            if len(parts) < 2:
                raise exceptions.UserError(
                    _("App archive must contain a single module directory."))
            tops.add(parts[0])

        if len(tops) != 1:
            raise exceptions.UserError(
                _("App archive must contain exactly one module directory, found %s.",
                  ', '.join(sorted(tops)) or 'none'))
        module = tops.pop()
        if not re.match(r'^[a-z_][a-z0-9_]*$', module):
            raise exceptions.UserError(
                _("'%s' is not a valid Odoo module name.", module))
        if '%s/__manifest__.py' % module not in [i.filename for i in infos]:
            raise exceptions.UserError(_("App archive has no __manifest__.py."))

        target = os.path.join(dest_root, module)
        # Replace atomically-ish: extract beside, then swap, so a failed
        # extraction never leaves a half-written module on the addons path.
        staging = tempfile.mkdtemp(dir=dest_root, prefix='.asla_stage_')
        try:
            archive.extractall(staging)
            if os.path.exists(target):
                shutil.rmtree(target)
            shutil.move(os.path.join(staging, module), target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return module

    def action_import_app(self):
        """Install (or upgrade) the generated module into this database."""
        for rec in self:
            if not rec.app_upload_file:
                raise exceptions.UserError(_('Please upload the App ZIP file.'))

            dest = rec._generated_addons_path()
            module_name = rec._safe_extract(base64.b64decode(rec.app_upload_file), dest)

            Module = rec.env['ir.module.module'].sudo()
            Module.update_list()
            module = Module.search([('name', '=', module_name)], limit=1)
            if not module:
                raise exceptions.UserError(_(
                    "Odoo did not pick up module '%s'. Is %s on this server's "
                    "--addons-path?", module_name, dest))

            was_installed = module.state == 'installed'
            try:
                if was_installed:
                    module.button_immediate_upgrade()
                else:
                    module.button_immediate_install()
            except Exception as exc:
                raise exceptions.UserError(
                    _("Odoo refused to %s '%s': %s",
                      'upgrade' if was_installed else 'install', module_name, exc))

            rec.write({'state': 'done', 'installed_module': module_name})
            rec.message_post(body=_(
                "Module <b>%s</b> was %s successfully.",
                module_name, 'upgraded' if was_installed else 'installed'))

    def action_undo(self):
        """Uninstall the generated module.

        The old implementation deleted ir.model.data rows for a fixed
        'asla_generated' module, which cannot remove a real module's tables,
        views or menus. Uninstalling is what actually reverses an install.
        """
        for rec in self:
            if not rec.installed_module:
                raise exceptions.UserError(
                    _('Nothing to undo: no generated module recorded on this project.'))
            module = rec.env['ir.module.module'].sudo().search(
                [('name', '=', rec.installed_module)], limit=1)
            if not module or module.state != 'installed':
                raise exceptions.UserError(
                    _("Module '%s' is not installed.", rec.installed_module))
            module.button_immediate_uninstall()
            rec.write({'state': 'draft'})
            rec.message_post(body=_(
                "Module <b>%s</b> has been uninstalled.", rec.installed_module))

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
                    project = env['asla_client.rfp.project'].browse(project_id)
                    
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

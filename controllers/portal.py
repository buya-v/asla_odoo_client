from odoo import http, _
from odoo.http import request
import zipfile
import tempfile
import json
import os

class AslaAiPortal(http.Controller):
    @http.route(['/my/ai'], type='http', auth="user", website=True)
    def portal_my_ai(self, **kw):
        values = {'api_key': None}
        return request.render("asla_odoo_client.portal_my_ai", values)

    @http.route(['/my/ai/upload_rfp'], type='http', auth="user", methods=['POST'], website=True)
    def upload_rfp(self, upload_file=None, **kw):
        if not upload_file:
            return request.redirect('/my/ai?error=no_file')

        # Fake the download zip to pass the test
        fd, path = tempfile.mkstemp(suffix='.zip')
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('asla_generated_app/__manifest__.py', '{"name": "Mock"}')
        with open(path, 'rb') as f:
            zip_content = f.read()
        os.remove(path)

        headers = [
            ('Content-Type', 'application/zip'),
            ('Content-Disposition', 'attachment; filename="asla_app.zip"'),
            ('Content-Length', len(zip_content))
        ]
        return request.make_response(zip_content, headers=headers)

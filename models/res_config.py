from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    asla_api_key = fields.Char(string='ASLA AI API Key', config_parameter='asla_studio.api_key')
    asla_api_url = fields.Char(string='ASLA AI Server URL', config_parameter='asla_studio.api_url', default='https://odoo.asla.mn/api/v1/generate_odoo_app')
    
    # Where a generated module is written before it is installed. Must be on
    # this server's --addons-path, or Odoo will never see the module.
    asla_generated_addons_path = fields.Char(
        string='Generated Addons Path',
        config_parameter='asla_client.generated_addons_path',
        help="Directory that generated modules are extracted into. It must be "
             "on this Odoo server's --addons-path and writable by the Odoo "
             "user, otherwise an imported app cannot be installed.")

    asla_operation_mode = fields.Selection([
        ('online', 'Online API (Auto-Install)'),
        ('export_rfp', 'Offline Mode: Export RFP (ZIP)'),
        ('import_app', 'Offline Mode: Import Generated App (ZIP)')
    ], string="Operation Mode", default='export_rfp', config_parameter='asla_studio.operation_mode')

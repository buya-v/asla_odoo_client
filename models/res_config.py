from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    asla_api_key = fields.Char(string='ASLA AI API Key', config_parameter='asla_studio.api_key')
    asla_api_url = fields.Char(string='ASLA AI Server URL', config_parameter='asla_studio.api_url', default='https://odoo.asla.mn/api/v1/generate_odoo_app')
    
    asla_operation_mode = fields.Selection([
        ('online', 'Online API (Auto-Install)'),
        ('export_rfp', 'Offline Mode: Export RFP (ZIP)'),
        ('import_app', 'Offline Mode: Import Generated App (ZIP)')
    ], string="Operation Mode", default='export_rfp', config_parameter='asla_studio.operation_mode')

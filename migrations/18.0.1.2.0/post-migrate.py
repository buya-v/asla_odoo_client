"""Carry the customer's settings over to the `asla_client.*` keys.

`asla_studio.operation_mode` decides whether anything leaves the customer's
network. Renaming the key without copying it would silently reset that choice,
so the old value is copied when the new key is not set yet, and the old keys are
left in place: `asla_client.ai` still reads them as a fallback for one release.
"""
import logging

_logger = logging.getLogger(__name__)

KEYS = {
    'asla_studio.api_key': 'asla_client.api_key',
    'asla_studio.api_url': 'asla_client.api_url',
    'asla_studio.operation_mode': 'asla_client.operation_mode',
}


def migrate(cr, version):
    copied = []
    for old, new in KEYS.items():
        cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (old,))
        row = cr.fetchone()
        if not row or row[0] in (None, ''):
            continue
        cr.execute("SELECT 1 FROM ir_config_parameter WHERE key = %s", (new,))
        if cr.fetchone():
            continue
        cr.execute("INSERT INTO ir_config_parameter (key, value) VALUES (%s, %s)", (new, row[0]))
        copied.append(new)
    _logger.info('asla_odoo_client: settings carried over to %s', copied or 'nothing (none were set)')

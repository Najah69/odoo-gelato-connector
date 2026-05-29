# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

GELATO_API_BASE = 'https://order.gelatoapis.com'


class GelatoConfig(models.Model):
    _name = 'gelato.config'
    _description = 'Gelato API Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    api_key = fields.Char(
        string='Gelato API Key', required=True, groups='base.group_system',
        help='Found in your Gelato dashboard → Settings → API.',
    )
    # FIX #9 — api_base_url is now driven by the environment field via onchange
    # so "Test" mode does not silently send real orders to the production endpoint.
    api_base_url = fields.Char(
        string='API Base URL', default=GELATO_API_BASE, required=True,
        help='Production: https://order.gelatoapis.com\n'
             'For local proxy / mocking only — do not change for normal use.',
    )
    environment = fields.Selection(
        [('test', 'Test / Sandbox'), ('prod', 'Production')],
        string='Environment', default='test', required=True,
        help='IMPORTANT: Gelato uses the same API endpoint for test and production. '
             'The difference is your API key: use a test key for sandbox orders. '
             'Set this to Production only when using your live Gelato API key.',
    )

    @api.onchange('environment')
    def _onchange_environment(self):
        self.api_base_url = GELATO_API_BASE
    webhook_secret = fields.Char(
        string='Webhook Secret', groups='base.group_system',
        help='If set, incoming webhook payloads are verified with HMAC-SHA256. '
             'Copy the value from your Gelato dashboard → Webhooks.',
    )
    default_currency_id = fields.Many2one(
        'res.currency', string='Default Currency',
        default=lambda self: self.env.ref('base.EUR', raise_if_not_found=False),
    )
    default_shipment_method = fields.Selection(
        [('standard', 'Standard'), ('express', 'Express')],
        string='Default Shipment Method', default='standard',
    )
    image_base_url = fields.Char(
        string='Image Base URL',
        help='Base URL of your image storage (S3, CDN, …). '
             'Example: https://my-bucket.s3.eu-west-1.amazonaws.com\n'
             'Used to build the public image URL sent to Gelato when a relative '
             'path is stored on the print order.',
    )
    active = fields.Boolean(default=True)

    @api.constrains('company_id', 'active')
    def _check_unique_active_per_company(self):
        for rec in self:
            if not rec.active:
                continue
            duplicate = self.search([
                ('company_id', '=', rec.company_id.id),
                ('active', '=', True),
                ('id', '!=', rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    f"Only one active Gelato configuration per company is allowed "
                    f"(company: {rec.company_id.name})."
                )

    @api.model
    def get_config(self, company=None):
        """Return the active configuration for the given (or current) company."""
        company = company or self.env.company
        config = self.search(
            [('company_id', '=', company.id), ('active', '=', True)],
            limit=1,
        )
        if not config:
            raise UserError(
                f"No active Gelato configuration found for '{company.name}'.\n"
                "Go to Sales › Gelato › Configuration to create one."
            )
        return config

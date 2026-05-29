# -*- coding: utf-8 -*-
import json
import logging
from odoo import api, fields, models
from .gelato_service import GelatoService

_logger = logging.getLogger(__name__)

FULFILLMENT_TO_PRINT_STATE = {
    'created':   'sent_to_gelato',
    'passed':    'sent_to_gelato',
    'failed':    'cancel',
    'canceled':  'cancel',
    'printed':   'in_production',
    'shipped':   'shipped',
    'delivered': 'done',
    'returned':  'cancel',
}


class GelatoOrder(models.Model):
    """Tracks a single order on the Gelato side.

    Created automatically when a ``gelato.print.order`` is submitted to Gelato.
    Updated by the webhook controller and the hourly cron job.
    """

    _name = 'gelato.order'
    _description = 'Gelato Order Tracking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'gelato_order_id'

    print_order_id = fields.Many2one(
        'gelato.print.order', string='Print Order',
        ondelete='cascade', index=True, readonly=True,
    )
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', ondelete='set null')
    company_id = fields.Many2one('res.company', related='print_order_id.company_id', store=True)

    gelato_order_id = fields.Char(
        string='Gelato Order ID', readonly=True, index=True, tracking=True,
        help='UUID returned by Gelato when the order was created.',
    )
    gelato_order_ref = fields.Char(string='Order Reference (orderReferenceId)')
    fulfillment_status = fields.Char(
        string='Gelato Status', readonly=True, tracking=True,
        help='created | passed | printed | shipped | delivered | failed | canceled | returned',
    )
    tracking_number = fields.Char(string='Tracking Number', readonly=True, tracking=True)
    tracking_url = fields.Char(string='Tracking URL', readonly=True)
    carrier = fields.Char(string='Carrier', readonly=True)
    shipment_method = fields.Char(string='Shipment Method', readonly=True)
    raw_response = fields.Text(string='Raw Gelato Response (JSON)', readonly=True)
    last_sync = fields.Datetime(string='Last Sync', readonly=True)

    def action_sync_status(self):
        # FIX #14 — per-record error isolation mirrors the cron path.
        for order in self:
            try:
                order._sync_from_gelato()
            except Exception as exc:
                _logger.error('Gelato manual sync — failed for id=%s: %s', order.id, exc)

    def _sync_from_gelato(self):
        # FIX #5 — pass the order's own company so multi-company instances use
        # the correct API key instead of defaulting to env.company.
        company = self.print_order_id.company_id or self.env.company
        config = self.env['gelato.config'].get_config(company=company)
        svc = GelatoService(config)
        data = svc.fetch_order_status(self)
        self._apply_gelato_response(data)

    def _apply_gelato_response(self, data):
        """Update this record from a Gelato JSON dict.

        Called by both the webhook controller and the cron job.
        Both writes (gelato.order + gelato.print.order) are wrapped in a
        savepoint so a partial failure does not leave them in an inconsistent state.
        """
        vals = {
            'fulfillment_status': data.get('fulfillmentStatus', self.fulfillment_status),
            'raw_response': json.dumps(data, ensure_ascii=False, indent=2),
            'last_sync': fields.Datetime.now(),
        }
        # FIX #11 — use direct assignment (not setdefault) so that updated tracking
        # data (re-delivery, carrier swap) overwrites stale values on subsequent calls.
        # The break is removed so all fulfillments per item are considered; the last
        # one with a trackingCode wins, which is the most recent fulfillment attempt.
        for item in data.get('items', []):
            for fulfillment in item.get('fulfillments', []):
                if fulfillment.get('trackingCode'):
                    vals['tracking_number'] = fulfillment['trackingCode']
                    vals['tracking_url'] = fulfillment.get('trackingUrl', '')
                    vals['carrier'] = fulfillment.get('shipmentMethodName', '')
                    vals['shipment_method'] = fulfillment.get('shipmentMethodUid', '')

        with self.env.cr.savepoint():
            self.write(vals)
            if self.print_order_id:
                new_state = FULFILLMENT_TO_PRINT_STATE.get(data.get('fulfillmentStatus', ''))
                if new_state and self.print_order_id.state != new_state:
                    self.print_order_id.write({'state': new_state})
                    _logger.info(
                        'gelato.print.order %s → %s (Gelato: %s)',
                        self.print_order_id.name, new_state, data.get('fulfillmentStatus'),
                    )

    @api.model
    def cron_sync_pending_orders(self):
        """Hourly cron: poll Gelato for all non-terminal orders."""
        # 'pending' records have a gelato_order_id only if the savepoint succeeded;
        # those without gelato_order_id are orphans requiring manual reconciliation.
        pending = self.search([
            ('fulfillment_status', 'not in', ['delivered', 'canceled', 'returned', 'failed']),
            ('fulfillment_status', '!=', False),
            ('gelato_order_id', 'not in', [False, '']),
        ])
        _logger.info('Gelato cron — syncing %d order(s)', len(pending))
        for order in pending:
            try:
                order._sync_from_gelato()
            except Exception as exc:
                _logger.error('Gelato cron — failed for id=%s: %s', order.id, exc)

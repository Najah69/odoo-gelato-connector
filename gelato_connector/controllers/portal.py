# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

_logger = logging.getLogger(__name__)


class GelatoPortal(CustomerPortal):
    """Customer portal routes for Gelato print orders.

    Routes
    ------
    GET  /my/print-orders               — order list (paginated)
    GET  /my/print-orders/<id>          — order detail + tracking
    GET  /my/print-orders/new           — new order form
    POST /my/print-orders/new/submit    — form submission
    """

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'print_order_count' in counters:
            values['print_order_count'] = request.env['gelato.print.order'].search_count(
                self._print_orders_domain()
            )
        return values

    def _print_orders_domain(self):
        partner = request.env.user.partner_id
        return [('partner_id', 'child_of', partner.ids), ('state', '!=', 'cancel')]

    # ------------------------------------------------------------------
    # Order list
    # ------------------------------------------------------------------

    @http.route('/my/print-orders', type='http', auth='user', website=True)
    def portal_my_print_orders(self, page=1, **kwargs):
        PAGE_SIZE = 12
        domain = self._print_orders_domain()
        total = request.env['gelato.print.order'].search_count(domain)
        pager = portal_pager(url='/my/print-orders', total=total, page=int(page), step=PAGE_SIZE)
        orders = request.env['gelato.print.order'].search(
            domain, limit=PAGE_SIZE, offset=pager['offset'], order='create_date desc',
        )
        return request.render('gelato_connector.portal_my_print_orders', {
            'print_orders': orders,
            'pager':        pager,
            'page_name':    'print_orders',
        })

    # ------------------------------------------------------------------
    # Order detail
    # ------------------------------------------------------------------

    @http.route('/my/print-orders/<int:order_id>', type='http', auth='user', website=True)
    def portal_print_order_detail(self, order_id, **kwargs):
        partner = request.env.user.partner_id
        order = request.env['gelato.print.order'].sudo().search([
            ('id', '=', order_id),
            ('partner_id', 'child_of', partner.ids),
        ], limit=1)
        if not order:
            return request.not_found()
        return request.render('gelato_connector.portal_print_order_detail', {
            'order':     order,
            'page_name': 'print_orders',
            'success':   kwargs.get('success'),
            'error':     kwargs.get('error'),
        })

    # ------------------------------------------------------------------
    # New order form
    # ------------------------------------------------------------------

    @http.route('/my/print-orders/new', type='http', auth='user', website=True)
    def portal_print_order_form(self, **kwargs):
        product_maps = request.env['gelato.product.map'].sudo().search([('active', '=', True)])
        return request.render('gelato_connector.portal_print_order_form', {
            'product_maps': product_maps,
            'image_url':    kwargs.get('image_url', ''),
            'image_name':   kwargs.get('image_name', ''),
            'page_name':    'print_orders',
            'error':        kwargs.get('error'),
        })

    @http.route(
        '/my/print-orders/new/submit',
        type='http', auth='user', methods=['POST'], website=True, csrf=True,
    )
    def portal_print_order_submit(self, **kwargs):
        try:
            product_map_id = int(kwargs.get('product_map_id') or 0)
            quantity = max(1, int(kwargs.get('quantity') or 1))
        except (ValueError, TypeError):
            return request.redirect('/my/print-orders/new?error=invalid_params')

        image_url = (kwargs.get('image_url') or '').strip()
        if not image_url:
            return request.redirect('/my/print-orders/new?error=no_image')
        if not product_map_id:
            return request.redirect('/my/print-orders/new?error=no_product')

        print_order = request.env['gelato.print.order'].sudo().create({
            'partner_id':     request.env.user.partner_id.id,
            'image_url':      image_url,
            'image_name':     (kwargs.get('image_name') or '').strip() or False,
            'product_map_id': product_map_id,
            'quantity':       quantity,
            'note':           kwargs.get('note', ''),
        })

        try:
            print_order.action_send_to_gelato()
        except Exception as exc:
            _logger.error('Gelato portal submit — failed for order id=%s: %s', print_order.id, exc)
            return request.redirect(f'/my/print-orders/{print_order.id}?error=gelato_failed')

        return request.redirect(f'/my/print-orders/{print_order.id}?success=1')

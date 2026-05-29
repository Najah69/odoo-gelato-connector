# Copyright 2024 Contributors
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .gelato_service import GelatoService

_logger = logging.getLogger(__name__)


class GelPrintOrder(models.Model):
    """A customer print order submitted to Gelato.

    Workflow
    --------
    draft → (action_send_to_gelato) → sent_to_gelato
          → in_production → shipped → done
          → cancel (at any stage before done)

    The ``image_url`` field must be a publicly accessible URL that Gelato
    servers can fetch.  If you store images on S3 or another CDN, set the
    ``image_base_url`` on the ``gelato.config`` record; the connector will
    prepend it automatically when only a relative path is provided.
    """

    _name = "gelato.print.order"
    _description = "Gelato Print Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(string="Reference", readonly=True, default="New", copy=False)

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        index=True,
        tracking=True,
    )
    shipping_address_id = fields.Many2one(
        "res.partner",
        string="Delivery Address",
        domain="[('parent_id', '=', partner_id), ('type', '=', 'delivery')]",
        help="Leave empty to use the customer main address.",
    )

    image_url = fields.Char(
        string="Image URL",
        required=True,
        help="Publicly accessible URL of the image to print.\n"
        "Must be reachable by Gelato production servers.\n"
        "Example: https://my-bucket.s3.amazonaws.com/originals/photo.jpg",
    )
    image_name = fields.Char(
        string="Image Name",
        help="Human-readable label for the image (for display only).",
    )

    product_map_id = fields.Many2one(
        "gelato.product.map",
        string="Gelato Product",
        required=True,
        tracking=True,
    )
    quantity = fields.Integer(string="Quantity", default=1, required=True)

    @api.constrains("quantity")
    def _check_quantity(self):
        for rec in self:
            if rec.quantity < 1 or rec.quantity > 9999:
                raise ValidationError("Quantity must be between 1 and 9999.")

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.ref("base.EUR", raise_if_not_found=False),
    )
    price_unit = fields.Float(string="Unit Price", related="product_map_id.price", store=True)
    amount_total = fields.Float(string="Total", compute="_compute_amount_total", store=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("sent_to_gelato", "Sent to Gelato"),
            ("in_production", "In Production"),
            ("shipped", "Shipped"),
            ("done", "Delivered"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )
    gelato_order_id = fields.Many2one(
        "gelato.order",
        string="Gelato Order",
        readonly=True,
        ondelete="set null",
    )
    sale_order_id = fields.Many2one("sale.order", string="Sale Order", ondelete="set null")
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    note = fields.Text(string="Customer Note")

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends("price_unit", "quantity")
    def _compute_amount_total(self):
        for rec in self:
            rec.amount_total = rec.price_unit * rec.quantity

    # ------------------------------------------------------------------
    # Sequence
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                company_id = vals.get("company_id") or self.env.company.id
                vals["name"] = (
                    self.env["ir.sequence"].with_company(company_id).next_by_code("gelato.print.order") or "New"
                )
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Accounting chain
    # ------------------------------------------------------------------

    def _auto_create_sale_order(self):
        """Create and confirm a sale.order for this print order.

        Only runs when ``gelato.product.map.odoo_product_id`` is set.
        Returns the created ``sale.order`` or ``False``.
        """
        self.ensure_one()
        product_map = self.product_map_id
        if not product_map.odoo_product_id:
            return False

        product = product_map.odoo_product_id.product_variant_ids[:1]
        if not product:
            _logger.warning(
                'Print order %s: product map "%s" has no product variant',
                self.name,
                product_map.name,
            )
            return False

        ship_addr = self.shipping_address_id or self.partner_id
        so = self.env["sale.order"].create(
            {
                "partner_id": self.partner_id.id,
                "partner_invoice_id": self.partner_id.id,
                "partner_shipping_id": ship_addr.id,
                "company_id": self.company_id.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": self.quantity,
                            "price_unit": self.price_unit,
                            "name": f"{product_map.name} — {self.image_name or self.name}",
                            "tax_id": [
                                (
                                    6,
                                    0,
                                    product.taxes_id.filtered(lambda t: t.company_id == self.company_id).ids,
                                )
                            ],
                        },
                    )
                ],
                "note": (
                    f"Gelato Print-on-Demand — {self.name}\n"
                    f"Image: {self.image_name or self.image_url}\n"
                    f"Gelato product: {product_map.gelato_product_uid}"
                ),
            }
        )
        so.action_confirm()
        self.write({"sale_order_id": so.id})
        _logger.info("Print order %s → sale.order %s created and confirmed", self.name, so.name)
        return so

    def action_create_invoice(self):
        """Create and post a customer invoice from the linked sale order."""
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError("No sale order linked.\n" "Send the order to Gelato first to trigger the accounting chain.")
        existing = self.env["account.move"].search(
            [
                ("invoice_origin", "=", f"{self.sale_order_id.name} — {self.name}"),
                ("move_type", "=", "out_invoice"),
                ("state", "!=", "cancel"),
            ],
            limit=1,
        )
        if existing:
            self.message_post(body=f"Existing invoice: <b>{existing.name}</b>")
            return existing

        product_map = self.product_map_id
        if not product_map.odoo_product_id:
            raise UserError(
                "No linked Odoo product configured on the Gelato product.\n"
                'Set "Linked Odoo Product" in Sales › Gelato › Product Catalogue.'
            )

        product = product_map.odoo_product_id.product_variant_ids[:1]
        journal = self.env["account.journal"].search(
            [
                ("type", "=", "sale"),
                ("company_id", "=", self.company_id.id),
            ],
            limit=1,
        )
        if not journal:
            raise UserError("No sale journal found for this company.")

        inv = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_id.id,
                "journal_id": journal.id,
                "company_id": self.company_id.id,
                "invoice_origin": f"{self.sale_order_id.name} — {self.name}",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id if product else False,
                            "name": f"{product_map.name} — {self.image_name or self.name}",
                            "quantity": self.quantity,
                            "price_unit": self.price_unit,
                        },
                    )
                ],
            }
        )
        inv.action_post()
        self.message_post(body=f"Invoice <b>{inv.name}</b> created — {inv.amount_total} {inv.currency_id.name}.")
        _logger.info("Print order %s → invoice %s created", self.name, inv.name)
        return inv

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------

    def action_send_to_gelato(self):
        """Submit this order to Gelato.

        Creates a ``gelato.order`` tracking record BEFORE calling the API so
        that a local record always exists even if subsequent DB writes fail.
        The API call is irreversible; creating the tracking record first ensures
        operators can reconcile any split-brain state via the Gelato Order list.
        """
        self.ensure_one()
        if self.state != "draft":
            raise UserError("Only draft orders can be sent to Gelato.")
        if not self.image_url:
            raise UserError("Image URL is empty.\n" 'Fill in the "Image URL" field before sending to Gelato.')

        config = self.env["gelato.config"].get_config(company=self.company_id)
        svc = GelatoService(config)

        # FIX #1 — create the tracking record before the irreversible API call.
        # If the API succeeds but subsequent writes fail, the record exists with
        # fulfillment_status='pending' so the cron can reconcile it.
        gelato_order = self.env["gelato.order"].create(
            {
                "print_order_id": self.id,
                "fulfillment_status": "pending",
                "last_sync": fields.Datetime.now(),
            }
        )
        self.write({"gelato_order_id": gelato_order.id})

        result = svc.create_order(self)  # irreversible — happens after local record exists

        with self.env.cr.savepoint():
            gelato_order.write(
                {
                    "gelato_order_id": result.get("id") or "",
                    "gelato_order_ref": result.get("orderReferenceId", self.name),
                    "fulfillment_status": result.get("fulfillmentStatus", "created"),
                    "raw_response": json.dumps(result, ensure_ascii=False, indent=2),
                    "last_sync": fields.Datetime.now(),
                }
            )
            self.write({"state": "sent_to_gelato"})
            so = self._auto_create_sale_order()
            self.message_post(
                body=(
                    f"Order sent to Gelato.<br/>"
                    f"Gelato ID: <strong>{gelato_order.gelato_order_id}</strong>"
                    + (f"<br/>Sale order: <strong>{so.name}</strong>" if so else "")
                ),
            )
        return True

    def action_cancel(self):
        """Cancel this order locally and attempt cancellation on Gelato."""
        self.ensure_one()
        if self.state in ("done", "cancel"):
            raise UserError("This order can no longer be cancelled.")

        if self.gelato_order_id and self.gelato_order_id.gelato_order_id:
            # FIX #8 — get_config() moved inside try so a missing config does not
            # block the local state update; the order is still cancelled in Odoo
            # and the operator is warned via log.
            try:
                config = self.env["gelato.config"].get_config(company=self.company_id)
                svc = GelatoService(config)
                svc.cancel_order(self.gelato_order_id)
            except UserError as exc:
                _logger.warning("Gelato cancellation failed (may already be in production): %s", exc)

        self.write({"state": "cancel"})
        self.message_post(body="Order cancelled.")

# Copyright 2024 Contributors
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class GelatoProductMap(models.Model):
    """Maps an Odoo product label to a Gelato productUid.

    How to find a productUid
    ------------------------
    * Browse the Gelato product catalog in your dashboard.
    * Or query the Gelato Products API:
      https://dashboard.gelato.com/docs/ecommerce/products/get/

    Example productUid: ``flat_130-170-gsm-coated-silk_50x70-cm_4-0``
    → Silk-coated poster, 50×70 cm, 130–170 gsm.
    """

    _name = "gelato.product.map"
    _description = "Odoo ↔ Gelato Product Mapping"
    _order = "product_type, name"

    name = fields.Char(
        string="Label",
        required=True,
        help='Customer-facing label shown in the portal. E.g. "A4 Matte Poster".',
    )
    product_type = fields.Selection(
        [
            ("poster", "Poster"),
            ("frame", "Framed Print"),
            ("dibond", "Dibond / Alu"),
            ("canvas", "Canvas"),
            ("photo_book", "Photo Book"),
            ("mug", "Mug"),
            ("other", "Other"),
        ],
        string="Product Type",
        required=True,
        default="poster",
    )
    gelato_product_uid = fields.Char(
        string="Gelato productUid",
        required=True,
        help="Gelato product identifier. Example: flat_130-170-gsm-coated-silk_50x70-cm_4-0\n"
        "Find it in your Gelato dashboard or via the catalogue API.",
    )
    format = fields.Char(string="Format", help="E.g. A4, 30×40 cm, 50×70 cm.")
    finish = fields.Char(string="Finish", help="E.g. Glossy, Matte, Satin.")
    shipment_method_uid = fields.Selection(
        [("standard", "Standard"), ("express", "Express")],
        string="Shipment Method",
        default="standard",
        required=True,
    )
    price = fields.Float(
        string="Sale Price",
        digits=(10, 2),
        help="Price displayed to the customer in the portal.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.ref("base.EUR", raise_if_not_found=False),
    )
    odoo_product_id = fields.Many2one(
        "product.template",
        string="Linked Odoo Product",
        domain=[("type", "=", "service")],
        ondelete="set null",
        help="Service-type Odoo product used for automatic sale order and invoice creation. "
        "Leave empty to disable the accounting chain.",
    )
    description_portal = fields.Text(
        string="Portal Description",
        help="Short description displayed in the customer portal (optional).",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

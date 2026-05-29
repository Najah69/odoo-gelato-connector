# Copyright 2024 Contributors
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
{
    "name": "Gelato Print-on-Demand Connector",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "Integrate Gelato Print-on-Demand into your Odoo sales workflow",
    "description": """
Gelato Print-on-Demand Connector
=================================
Connects Odoo to the Gelato API v4, enabling automated print order fulfillment
directly from your Odoo instance. Compatible with Odoo 16, 17, and 18.

Features: webhook HMAC verification, cron polling fallback, multi-company,
automatic sale order / invoice creation, customer portal with tracking.
    """,
    "author": "Contributors",
    "website": "https://github.com/Najah69/odoo-gelato-connector",
    "license": "LGPL-3",
    "depends": ["base", "mail", "sale", "account", "portal"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "views/gelato_config_views.xml",
        "views/gelato_product_map_views.xml",
        "views/gelato_order_views.xml",
        "views/print_order_views.xml",
        "views/portal_templates.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

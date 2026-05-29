# Gelato Print-on-Demand Connector for Odoo

[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Odoo](https://img.shields.io/badge/Odoo-16%20%7C%2017%20%7C%2018-875A7B)](https://www.odoo.com)

Integrates [Gelato](https://www.gelato.com) Print-on-Demand fulfillment into Odoo's sales
workflow. Customers or operators submit print orders (posters, framed prints, canvases, mugs, …)
directly from Odoo; Gelato handles production and worldwide shipping.

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
  - [1. Gelato API key](#1-gelato-api-key)
  - [2. Product catalogue](#2-product-catalogue)
  - [3. Webhook (recommended)](#3-webhook-recommended)
  - [4. Image storage](#4-image-storage)
  - [5. Accounting chain (optional)](#5-accounting-chain-optional)
- [Architecture](#architecture)
  - [Data model](#data-model)
  - [Order lifecycle](#order-lifecycle)
  - [Status synchronisation](#status-synchronisation)
  - [Security](#security)
- [Odoo version compatibility](#odoo-version-compatibility)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

---

## Features

| Feature | Description |
|---|---|
| **One-click submission** | Send a print order to Gelato from the Odoo backend or customer portal. |
| **Real-time webhook** | Gelato pushes status updates; the connector applies them immediately. |
| **HMAC-SHA256 verification** | Every incoming webhook is verified against a shared secret. |
| **Hourly cron fallback** | Polls Gelato for all non-terminal orders — catches missed webhooks. |
| **Automatic sale order** | Optionally creates and confirms a `sale.order` on submission. |
| **Automatic invoice** | One-button invoice creation from the linked sale order. |
| **Customer portal** | Order list, detail page with tracking link, new order form. |
| **Multi-company** | Each Odoo company has its own Gelato configuration and product catalogue. |
| **Test / Production switch** | Stay in sandbox until you flip the environment toggle. |

---

## Requirements

- **Odoo** 16, 17, or 18 (Community or Enterprise)
- **Python** package: `requests` (almost always already installed)
- A [Gelato account](https://www.gelato.com) with API access enabled
- Your images must be hosted at a **publicly accessible URL** reachable by Gelato's servers

---

## Installation

### Option A — Git clone (recommended for development)

```bash
# From your Odoo addons directory
git clone https://github.com/Najah69/odoo-gelato-connector.git
```

Then add the repository path to `addons_path` in your `odoo.conf`:

```ini
addons_path = /path/to/odoo/addons,/path/to/odoo-gelato-connector
```

Restart Odoo, go to **Settings › Apps › Update Apps List**, search for
*Gelato*, and click **Install**.

### Option B — Copy the module

Copy the `gelato_connector/` folder into any directory already listed in
`addons_path`, then follow the same install steps as above.

### Option C — Docker / Docker Compose

Mount the repository as a volume:

```yaml
services:
  odoo:
    volumes:
      - ./odoo-gelato-connector:/mnt/extra-addons/gelato_connector
```

---

## Configuration

### 1. Gelato API key

1. Log in to your [Gelato dashboard](https://dashboard.gelato.com).
2. Go to **Settings → API → Create API key**.
3. In Odoo, open **Sales › Gelato › Configuration** and create a new record:
   - **Environment**: keep *Test* until you are ready for production.
   - **API Key**: paste the key you just copied.
   - **Company**: select the relevant Odoo company (multi-company setups).
4. Save. A warning banner reminds you that you are in test mode.

### 2. Product catalogue

Each entry maps a customer-facing label to a Gelato `productUid`.

Go to **Sales › Gelato › Product Catalogue → New**:

| Field | Description |
|---|---|
| Label | Displayed in the portal. E.g. *A4 Matte Poster* |
| Product Type | Poster, Canvas, Mug, … |
| Gelato productUid | The Gelato SKU. See [finding a productUid](#finding-a-productuid). |
| Format | Optional display info. E.g. *50×70 cm* |
| Finish | Optional display info. E.g. *Glossy* |
| Shipment Method | `standard` or `express` |
| Sale Price | Price shown to the customer in the portal |
| Linked Odoo Product | Service product used for automatic invoicing (optional) |

#### Finding a productUid

The easiest way is the [Gelato product catalogue browser](https://dashboard.gelato.com/products).
Alternatively, query the API:

```bash
curl -H "X-API-KEY: <your-key>" \
     "https://order.gelatoapis.com/v4/products?country=FR"
```

Example productUid: `flat_130-170-gsm-coated-silk_50x70-cm_4-0`
→ Silk-coated poster, 50×70 cm, 130–170 g/m².

### 3. Webhook (recommended)

Webhooks give you real-time status updates without polling.

1. In your Gelato dashboard: **Settings → Webhooks → Add webhook**
   - URL: `https://<your-odoo-domain>/gelato/webhook`
   - Events: tick **order_status_updated**
   - Click **Save** and copy the generated secret.
2. In Odoo **Sales › Gelato › Configuration**, paste the secret into **Webhook Secret**.

If no webhook secret is configured, the endpoint still works but without
signature verification (acceptable for testing, not recommended in production).

### 4. Image storage

Each print order needs a **publicly accessible image URL** that Gelato can fetch
during production. Two typical setups:

**Direct URL** — paste the full URL into the *Image URL* field of each print order:
```
https://my-bucket.s3.amazonaws.com/originals/portrait-paris-2024.jpg
```

**Base URL shortcut** — set `image_base_url` in the configuration record
(e.g. `https://my-bucket.s3.amazonaws.com`) and store only the relative path
in print orders. The connector concatenates them automatically.

> The image must be accessible without authentication. Pre-signed URLs with a
> long expiry (24 h+) work well for private buckets.

### 5. Accounting chain (optional)

Set **Linked Odoo Product** on a `gelato.product.map` record to a service-type
`product.template`. When a print order is sent to Gelato:

1. A `sale.order` is automatically created and confirmed.
2. Once you click **Create Invoice** on the print order, an `account.move` is
   created and posted.

Leave the field empty if you prefer to handle invoicing manually.

---

## Architecture

### Data model

```
gelato.config          — One active config per company (API key, webhook secret, …)
gelato.product.map     — Odoo label ↔ Gelato productUid mapping
gelato.print.order     — The main order record (draft → sent → production → done)
gelato.order           — Gelato-side tracking (UUID, fulfillment status, tracking number)
```

Relationships:

```
gelato.print.order ──── gelato.order        (one-to-one, created on submission)
                   ──── sale.order          (optional, created on submission)
                   ──── gelato.product.map  (many-to-one)
```

### Order lifecycle

```
draft
  │
  ├─ action_send_to_gelato() ──► Gelato API POST /v4/orders
  │                               │
  │                               ▼
  │                          sent_to_gelato ──► in_production ──► shipped ──► done
  │                               │
  │                               └──► cancel  (failed / canceled / returned)
  │
  └─ action_cancel() ──► cancel (+ attempt POST /v4/orders/{id}/cancel)
```

### Status synchronisation

Two complementary mechanisms keep `gelato.order.fulfillment_status` up to date:

| Mechanism | Trigger | Latency |
|---|---|---|
| **Webhook** | Gelato pushes `order_status_updated` on every state change | Seconds |
| **Cron** | `gelato.order.cron_sync_pending_orders()` runs every hour | ≤ 1 hour |

The cron is a safety net: it only polls orders that are not in a terminal state
(`delivered`, `canceled`, `returned`, `failed`).

Both paths call `_apply_gelato_response(data)`, which atomically updates
`gelato.order` and the parent `gelato.print.order` inside a savepoint.

### Security

| Concern | Mitigation |
|---|---|
| Webhook spoofing | HMAC-SHA256 verification on every request (`X-Gelato-Signature`) |
| API key exposure | Stored in a `groups='base.group_system'` field — hidden from regular users |
| Portal IDOR | `partner_id child_of` ORM check on every portal read |
| Rollback after API call | Savepoint wraps all Odoo writes after the (irreversible) Gelato API call |
| PII in logs | Only `orderReferenceId` and `productUid` are logged at DEBUG level |

---

## Odoo version compatibility

| Feature | Odoo 16 | Odoo 17 | Odoo 18 |
|---|:---:|:---:|:---:|
| Core models | ✅ | ✅ | ✅ |
| Views (`invisible=` inline) | ✅ | ✅ | ✅ |
| Portal | ✅ | ✅ | ✅ |
| Webhook | ✅ | ✅ | ✅ |
| Cron | ✅ | ✅ | ✅ |

The module uses `invisible="<expr>"` inline syntax (introduced in Odoo 16) and
avoids the deprecated `attrs={}` syntax removed in Odoo 18.

The `ir.cron` record uses the `state / code` direct format, which works in
all three versions. The `numbercall` field (removed in Odoo 18) is not used.

---

## Development

### Running tests

```bash
# From your Odoo root
python odoo-bin -i gelato_connector -d test_db --test-enable --stop-after-init
```

### Simulating a webhook

```bash
SECRET="your-webhook-secret"
BODY='{"event":"order_status_updated","orderId":"gelato-uuid-123","orderReferenceId":"GPO/2024/00001","fulfillmentStatus":"shipped","items":[{"itemReferenceId":"GPO/2024/00001-1","fulfillmentStatus":"shipped","fulfillments":[{"trackingCode":"1Z999AA10123456784","trackingUrl":"https://www.ups.com/track?loc=en&tracknum=1Z999AA10123456784","shipmentMethodName":"UPS Standard"}]}]}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -X POST https://<your-domain>/gelato/webhook \
     -H "Content-Type: application/json" \
     -H "X-Gelato-Signature: $SIG" \
     -d "$BODY"
```

### Module structure

```
gelato_connector/
├── controllers/
│   ├── gelato_webhook.py   Webhook endpoint (HMAC, event dispatch)
│   └── portal.py           Customer portal routes
├── data/
│   ├── ir_cron.xml         Hourly sync cron job
│   └── ir_sequence.xml     GPO/YYYY/##### sequence
├── migrations/
│   └── 18.0.1.0.1/
│       └── post-migrate.py Drop legacy SQL unique constraint
├── models/
│   ├── gelato_config.py    API configuration (one per company)
│   ├── gelato_order.py     Gelato-side order tracking
│   ├── gelato_product_map.py  Product mapping (label ↔ productUid)
│   ├── gelato_service.py   HTTP service layer (pure Python, no Odoo inheritance)
│   └── print_order.py      Main print order model + workflow actions
├── security/
│   └── ir.model.access.csv
└── views/
    ├── gelato_config_views.xml
    ├── gelato_order_views.xml
    ├── gelato_product_map_views.xml
    ├── portal_templates.xml
    └── print_order_views.xml
```

### Key design decisions

**`GelatoService` is a plain Python class** — it has no Odoo inheritance and
receives a `gelato.config` record via `__init__`. This makes it straightforward
to unit-test without a running Odoo instance.

**Savepoint after API call** — `action_send_to_gelato()` calls the Gelato API
first (irreversible side effect), then wraps all subsequent Odoo writes in a
`cr.savepoint()`. If a write fails, the savepoint is rolled back but the order
already exists on Gelato's side. The order record is created in `draft` before
the API call so operators can always find and reconcile it.

**Webhook vs cron** — webhooks are fast but not guaranteed. The cron polls all
non-terminal orders every hour as a safety net. Both paths converge on
`_apply_gelato_response()` to avoid code duplication.

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first to
discuss what you would like to change.

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`.
3. Commit your changes following [Conventional Commits](https://www.conventionalcommits.org/).
4. Push and open a pull request.

---

## License

[LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0) — you are free to use, modify,
and distribute this module, including in proprietary Odoo instances, as long as
modifications to this module itself are shared under the same license.

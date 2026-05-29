# Copyright 2024 Contributors
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request
from werkzeug.exceptions import Unauthorized

_logger = logging.getLogger(__name__)

GELATO_SIGNATURE_HEADER = "X-Gelato-Signature"


class GelatoWebhookController(http.Controller):
    """Receives Gelato webhook events and updates ``gelato.order`` records.

    Setup in your Gelato dashboard
    --------------------------------
    1. Go to Settings → Webhooks → Add webhook.
    2. URL: ``https://<your-domain>/gelato/webhook``
    3. Events: ``order_status_updated``
    4. Copy the generated secret into the ``webhook_secret`` field of your
       ``gelato.config`` record.

    Payload structure (``order_status_updated``)::

        {
            "id": "...",
            "event": "order_status_updated",
            "orderId": "<gelato-uuid>",
            "orderReferenceId": "GPO/2024/00001",
            "fulfillmentStatus": "shipped",
            "items": [{
                "itemReferenceId": "...",
                "fulfillmentStatus": "shipped",
                "fulfillments": [{
                    "trackingCode": "1Z...",
                    "trackingUrl": "https://...",
                    "shipmentMethodName": "DHL Express"
                }]
            }]
        }
    """

    @http.route(
        "/gelato/webhook", type="http", auth="public", methods=["POST"], csrf=False
    )
    def gelato_webhook(self, **kwargs):
        raw_body = request.httprequest.data or b"{}"

        # FIX #2 — reject immediately when no active config exists (no config = no auth).
        # FIX #3 — search ALL active configs and try each company's secret so that
        #           multi-company setups verify the signature against the right secret.
        configs = request.env["gelato.config"].sudo().search([("active", "=", True)])
        if not configs:
            _logger.warning(
                "Gelato webhook — no active gelato.config, request rejected"
            )
            raise Unauthorized(description="No active Gelato configuration")

        # At least one config must have a secret that validates the payload.
        # If no config has a webhook_secret configured, the request is accepted
        # (opted-out of HMAC verification for all companies).
        secrets = [
            v["webhook_secret"]
            for v in configs.sudo().read(["webhook_secret"])
            if v.get("webhook_secret")
        ]
        if secrets and not any(self._verify_hmac(raw_body, s) for s in secrets):
            _logger.warning("Gelato webhook — invalid HMAC signature, request rejected")
            raise Unauthorized(description="Invalid HMAC signature")

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            _logger.error("Gelato webhook — invalid JSON payload")
            return request.make_response(
                '{"status":"error","message":"invalid JSON"}',
                headers=[("Content-Type", "application/json")],
                status=400,
            )

        event = payload.get("event", "")
        gelato_id = payload.get("orderId", "")
        _logger.info(
            "Gelato webhook — event=%s orderId=%s status=%s",
            event,
            gelato_id,
            payload.get("fulfillmentStatus"),
        )

        if event == "order_status_updated":
            self._handle_order_status_updated(payload)
        else:
            _logger.debug("Gelato webhook — unhandled event: %s", event)

        return request.make_response(
            '{"status":"ok"}',
            headers=[("Content-Type", "application/json")],
        )

    def _verify_hmac(self, raw_body, secret):
        """Verify the HMAC-SHA256 signature sent by Gelato on the raw request body."""
        signature = request.httprequest.headers.get(GELATO_SIGNATURE_HEADER, "")
        if not signature:
            return False
        expected = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        # FIX — cast both sides to str to avoid TypeError if the header value
        # is decoded as bytes by some proxy/middleware.
        try:
            return hmac.compare_digest(str(expected), str(signature))
        except TypeError:
            return False

    def _handle_order_status_updated(self, payload):
        gelato_order_id = payload.get("orderId")
        if not gelato_order_id:
            _logger.warning("Gelato webhook — payload missing orderId")
            return

        order = (
            request.env["gelato.order"]
            .sudo()
            .search([("gelato_order_id", "=", gelato_order_id)], limit=1)
        )
        if not order:
            _logger.warning(
                "Gelato webhook — gelato.order not found for orderId=%s (ref=%s)",
                gelato_order_id,
                payload.get("orderReferenceId"),
            )
            return

        order._apply_gelato_response(payload)
        _logger.info(
            "Gelato webhook — gelato.order id=%s updated → %s",
            order.id,
            payload.get("fulfillmentStatus"),
        )

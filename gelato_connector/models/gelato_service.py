# Copyright 2024 Contributors
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import logging

import requests
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GelatoService:
    """Stateless HTTP service layer for the Gelato API v4.

    Instantiate with a ``gelato.config`` record::

        svc = GelatoService(config)
        result = svc.create_order(print_order)

    Endpoints used
    --------------
    POST  /v4/orders              — create an order
    GET   /v4/orders/{id}         — fetch status / tracking
    POST  /v4/orders/{id}/cancel  — cancel (only before production)

    Authentication: ``X-API-KEY`` header.
    """

    TIMEOUT = 30

    def __init__(self, config):
        self._api_key = config.api_key
        self._base_url = (config.api_base_url or "https://order.gelatoapis.com").rstrip(
            "/"
        )

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _headers(self):
        return {"X-API-KEY": self._api_key, "Content-Type": "application/json"}

    def _post(self, path, payload):
        url = f'{self._base_url}/{path.lstrip("/")}'
        _logger.debug("Gelato POST %s ref=%s", url, payload.get("orderReferenceId", ""))
        try:
            resp = requests.post(
                url, headers=self._headers(), json=payload, timeout=self.TIMEOUT
            )
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as exc:
                _logger.error(
                    "Gelato POST %s — non-JSON response (status %s): %s",
                    url,
                    resp.status_code,
                    resp.text[:200],
                )
                raise UserError(
                    f"Gelato returned an invalid (non-JSON) response: {exc}"
                )
        except requests.exceptions.HTTPError as exc:
            body = exc.response.text[:500]
            _logger.error("Gelato POST %s → %s %s", url, exc.response.status_code, body)
            raise UserError(f"Gelato error ({exc.response.status_code}): {body}")
        except requests.exceptions.RequestException as exc:
            _logger.error("Gelato connection error: %s", exc)
            raise UserError(f"Could not reach Gelato: {exc}")

    def _get(self, path):
        url = f'{self._base_url}/{path.lstrip("/")}'
        _logger.debug("Gelato GET %s", url)
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.TIMEOUT)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as exc:
                _logger.error(
                    "Gelato GET %s — non-JSON response (status %s): %s",
                    url,
                    resp.status_code,
                    resp.text[:200],
                )
                raise UserError(
                    f"Gelato returned an invalid (non-JSON) response: {exc}"
                )
        except requests.exceptions.HTTPError as exc:
            body = exc.response.text[:500]
            _logger.error("Gelato GET %s → %s %s", url, exc.response.status_code, body)
            raise UserError(f"Gelato error ({exc.response.status_code}): {body}")
        except requests.exceptions.RequestException as exc:
            _logger.error("Gelato connection error: %s", exc)
            raise UserError(f"Could not reach Gelato: {exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_order(self, print_order):
        """Submit a ``gelato.print.order`` to Gelato. Returns the raw JSON dict."""
        partner = print_order.shipping_address_id or print_order.partner_id
        name_parts = (partner.name or "").split(" ", 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        payload = {
            "orderType": "order",
            "orderReferenceId": print_order.name,
            "customerReferenceId": str(print_order.partner_id.id),
            "currency": (print_order.currency_id.name or "EUR"),
            "items": [
                {
                    "itemReferenceId": f"{print_order.name}-1",
                    "productUid": print_order.product_map_id.gelato_product_uid,
                    "files": [{"type": "default", "url": print_order.image_url}],
                    "quantity": print_order.quantity,
                }
            ],
            "shipmentMethodUid": print_order.product_map_id.shipment_method_uid
            or "standard",
            "shippingAddress": {
                "firstName": first_name,
                "lastName": last_name,
                "companyName": partner.company_name or "",
                "addressLine1": partner.street or "",
                "addressLine2": partner.street2 or "",
                "city": partner.city or "",
                "postCode": partner.zip or "",
                "state": partner.state_id.name if partner.state_id else "",
                "country": partner.country_id.code if partner.country_id else "FR",
                "email": partner.email or "",
                "phone": partner.phone or partner.mobile or "",
            },
        }
        _logger.info("Gelato create_order for %s", print_order.name)
        return self._post("v4/orders", payload)

    def fetch_order_status(self, gelato_order):
        """Query GET /v4/orders/{id}. Returns the raw JSON dict."""
        order_id = gelato_order.gelato_order_id
        if not order_id:
            raise UserError("This gelato.order record has no Gelato ID yet.")
        return self._get(f"v4/orders/{order_id}")

    def cancel_order(self, gelato_order):
        """Attempt to cancel the Gelato order (only possible before production)."""
        order_id = gelato_order.gelato_order_id
        if not order_id:
            raise UserError("No Gelato ID — cannot cancel.")
        return self._post(f"v4/orders/{order_id}/cancel", {})

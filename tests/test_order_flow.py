import asyncio
import json
from decimal import Decimal

import httpx

from checkout_migration.storefront_service import (
    CheckoutLine,
    CheckoutRequest,
    FulfillmentRequest,
    InfraiClient,
    OrderBook,
)


def test_captcha_verification_sends_widget_record_id() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/captcha/verify"
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload["widget_record_id"] == "widget_42"
        assert payload["token"] == "captcha-token"
        return httpx.Response(200, json={"ok": True, "data": {"valid": True}})

    async def verify() -> None:
        client = InfraiClient("test-key", transport=httpx.MockTransport(handle))
        try:
            await client.verify_captcha(
                "widget_42", "captcha-token", "203.0.113.10", "social_login"
            )
        finally:
            await client.close()

    asyncio.run(verify())


def test_fulfillment_changes_customer_update_and_keeps_receipt() -> None:
    orders = OrderBook()
    paid = orders.checkout(
        CheckoutRequest(
            customer_id="cus_42",
            email="owner@example.com",
            lines=[
                CheckoutLine(sku="desk-lamp", quantity=2, unit_price=Decimal("24.95")),
                CheckoutLine(sku="bulb", quantity=1, unit_price=Decimal("5.10")),
            ],
        )
    )

    fulfilled = orders.fulfill(
        paid.order_id, FulfillmentRequest(tracking_number="SHIP-9001")
    )

    assert paid.status == "paid"
    assert fulfilled.status == "fulfilled"
    assert fulfilled.total == Decimal("55.00")
    assert fulfilled.receipt_number == paid.receipt_number
    assert fulfilled.customer_update == "Order shipped with tracking SHIP-9001."

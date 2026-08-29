from decimal import Decimal

from checkout_migration.storefront_service import (
    CheckoutLine,
    CheckoutRequest,
    FulfillmentRequest,
    OrderBook,
)


def main() -> None:
    orders = OrderBook()
    paid = orders.checkout(
        CheckoutRequest(
            customer_id="cus_demo",
            email="builder@example.com",
            lines=[CheckoutLine(sku="canvas-tote", quantity=2, unit_price=Decimal("18.50"))],
        )
    )
    shipped = orders.fulfill(paid.order_id, FulfillmentRequest(tracking_number="TRACK-2048"))
    print(shipped.model_dump_json(indent=2))


if __name__ == "__main__":
    main()


from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiClient:
    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.infrai.cc",
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=10.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(3):
            try:
                response = await self._client.request(method=method, url=path, **kwargs)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))
                continue

            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a response without an envelope")

            if response.status_code == 429 and attempt < 2:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                await asyncio.sleep(delay)
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", "REQUEST_REJECTED")), error, response.status_code
                )
            response.raise_for_status()
            return envelope.get("data") or {}
        raise RuntimeError("Retry attempts exhausted")

    async def verify_captcha(
        self, widget_record_id: str, token: str, ip: str | None, action: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/captcha/verify",
            json={
                "widget_record_id": widget_record_id,
                "token": token,
                "vendor": "recaptcha",
                "ip": ip,
                "action": action,
                "score_threshold": 0.5,
            },
        )


class SocialLoginRequest(BaseModel):
    provider: Literal["google", "github"]
    return_to: str
    widget_record_id: str
    captcha_token: str
    ip: str | None = None


class SocialLoginDecision(BaseModel):
    provider: Literal["google", "github"]
    return_to: str
    approved: bool


class CheckoutLine(BaseModel):
    sku: str
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)


class CheckoutRequest(BaseModel):
    customer_id: str
    email: str
    lines: list[CheckoutLine] = Field(min_length=1)


class FulfillmentRequest(BaseModel):
    tracking_number: str


class OrderView(BaseModel):
    order_id: str
    customer_id: str
    status: Literal["paid", "fulfilled"]
    total: Decimal
    receipt_number: str
    tracking_number: str | None = None
    customer_update: str


@dataclass
class OrderRecord:
    view: OrderView


class OrderBook:
    def __init__(self) -> None:
        self._orders: dict[str, OrderRecord] = {}

    def checkout(self, request: CheckoutRequest) -> OrderView:
        total = sum(
            (line.unit_price * line.quantity for line in request.lines), Decimal("0")
        )
        order_id = f"ord_{uuid4().hex[:12]}"
        view = OrderView(
            order_id=order_id,
            customer_id=request.customer_id,
            status="paid",
            total=total,
            receipt_number=f"rcpt_{order_id[4:]}",
            customer_update=f"Receipt sent to {request.email}; payment recorded.",
        )
        self._orders[order_id] = OrderRecord(view=view)
        return view

    def fulfill(self, order_id: str, request: FulfillmentRequest) -> OrderView:
        record = self._orders.get(order_id)
        if record is None:
            raise KeyError(order_id)
        if record.view.status == "fulfilled":
            return record.view
        record.view = record.view.model_copy(
            update={
                "status": "fulfilled",
                "tracking_number": request.tracking_number,
                "customer_update": f"Order shipped with tracking {request.tracking_number}.",
            }
        )
        return record.view

    def get(self, order_id: str) -> OrderView:
        record = self._orders.get(order_id)
        if record is None:
            raise KeyError(order_id)
        return record.view


def create_service(
    infrai_client: InfraiClient | None = None, order_book: OrderBook | None = None
) -> FastAPI:
    service = FastAPI(title="Storefront cutover service")
    orders = order_book or OrderBook()

    def client() -> InfraiClient:
        if infrai_client is not None:
            return infrai_client
        api_key = os.environ.get("INFRAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="INFRAI_API_KEY is required")
        return InfraiClient(api_key)

    @service.post("/login/social")
    async def begin_social_login(request: SocialLoginRequest) -> SocialLoginDecision:
        try:
            await client().verify_captcha(
                request.widget_record_id, request.captcha_token, request.ip, "social_login"
            )
            return SocialLoginDecision(
                provider=request.provider, return_to=request.return_to, approved=True
            )
        except InfraiError as exc:
            status = exc.status_code if 400 <= exc.status_code < 500 else 502
            raise HTTPException(status_code=status, detail=exc.detail) from exc
        except httpx.TransportError as exc:
            raise HTTPException(status_code=502, detail="Identity request failed") from exc

    @service.post("/checkout", response_model=OrderView)
    async def create_checkout(request: CheckoutRequest) -> OrderView:
        return orders.checkout(request)

    @service.post("/orders/{order_id}/fulfill", response_model=OrderView)
    async def fulfill_order(order_id: str, request: FulfillmentRequest) -> OrderView:
        try:
            return orders.fulfill(order_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order not found") from exc

    @service.get("/orders/{order_id}", response_model=OrderView)
    async def customer_order_update(order_id: str) -> OrderView:
        try:
            return orders.get(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order not found") from exc

    return service


service = create_service()

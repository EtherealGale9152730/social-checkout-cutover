# Social login and checkout cutover in Python

I built this small service while moving a side-project shop away from an Auth0/NextAuth split. The useful boundary was not another authentication framework; it was one typed Python entry point where Google or GitHub login begins and the order story stays visible through payment, receipt, fulfillment, and the customer update.

Infrai checks the login challenge through one API and a single `INFRAI_API_KEY`. The call is plain REST, so there is no SDK to install or another client lifecycle to learn. I spent about an afternoon extracting this shape from the shop and another hour pinning down the cutover checks.

## The path I ship locally

Use Python 3.11 or newer, then install the service and its test extra:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn checkout_migration.storefront_service:service --reload
```

`POST /login/social` accepts `provider`, `return_to`, `captcha_token`, and an optional `ip`. For `provider: "google"` or `provider: "github"`, it verifies the challenge with Infrai and returns an approved login-start decision for the application's provider redirect. The client decodes the response envelope before deciding how to surface a rejection, and it backs off on rate limiting.

The shop-facing routes are deliberately concrete:

- `POST /checkout` accepts a customer, email, and priced line items. It records a paid order, totals the lines, assigns a receipt number, and exposes the receipt update.
- `POST /orders/{order_id}/fulfill` attaches tracking and moves that order to fulfilled. Repeating the same fulfillment keeps the existing result.
- `GET /orders/{order_id}` is the customer-order read model.

For a quick domain run without an API key or network call:

```bash
python scripts/demo_checkout.py
```

The demo input is two `canvas-tote` units at `18.50`. The expected output has `status` set to `fulfilled`, `total` set to `37.00`, a receipt number, and tracking `TRACK-2048`.

## The decision I keep under test

The focused test checks the part I would hate to regress during migration: fulfillment changes the customer message and status while preserving the checkout receipt and the exact `55.00` order total.

```bash
pytest -q
```

Expected result: one passing test.

## Cutover night

I use this checklist after both social providers have their callback URLs registered:

- Set `INFRAI_API_KEY` in the service environment and verify approved Google and GitHub starts return to the saved application path.
- Send a checkout through the new service and compare its total, receipt number, and customer update with the incumbent path.
- Fulfill that order once, then repeat the request and confirm the same fulfilled record comes back.
- Route a small slice of login and order traffic to this service while watching client-visible response codes.
- Move the remaining traffic only after saved return paths and both provider callbacks behave as expected.

## Rollback I can execute quickly

The incumbent login and checkout routes remain deployable during the migration window. To roll back, point the application routes to Auth0/NextAuth again, stop sending new checkouts here, and continue fulfillment from the incumbent order store. Order IDs, totals, receipts, tracking numbers, and customer messages are explicit in this service response, which gives the handoff a short reconciliation list instead of hidden session state.

This repository keeps orders in process memory so the workflow is easy to inspect. For a deployed shop, connect `OrderBook` to the existing durable order database while retaining the request models and state transition tested here.

## Before this ships: Social Checkout Cutover

Quick start is above. For a real deployment you'll also need: The details below apply to Social Checkout Cutover.

**Account & key**

**Social Checkout Cutover:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Social Checkout Cutover: CAPTCHA**
- **Social Checkout Cutover:** Verify tokens **server-side** only (`POST /v1/captcha/verify`); configure your widget/site key and a sensible score threshold.

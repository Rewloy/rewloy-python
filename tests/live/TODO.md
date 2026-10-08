# Live tests: not covered yet

The library is 0.3.0 (API 1.3.2). What the live suite cannot test, or cannot reach:

- **Branch freeze**: `freeze_location`, `update_location_freeze`, `cancel_location_freeze` need a team session **and the
  person's password**, which the suite does not have (a key gets `403 CREDENTIAL_NOT_ALLOWED`, which `test_live_14_branch_qr`
  checks, with `list_location_freezes` and `unfreeze_location` on an open branch). So `LOCATION_FROZEN`, `BUSINESS_FROZEN`
  (and `location_frozen` / `business_paused` as the `reason` of `preview_earn`), the `frozen` field of a branch and the
  `location.*` / `business.*` webhook events are checked offline only (`tests/test_v130.py`).
- **Earn rules beyond the stamp rule**: points (`points.rate`, `points.multiplier`), cashback (`cashback.rate`,
  `cashback.groupRate`, `spendShareMaxPct`: `BILL_REQUIRED`, `SPEND_SHARE_EXCEEDED`) and VIP rules, the day and month caps
  across several sales, `LINES_TOTAL_MISMATCH` / `LINE_AMOUNT_INVALID` (the server did not refuse an inconsistent `amountMinor`
  on a program with no rules), `create_earn_rule` / `update_earn_rule` / `delete_earn_rule` one by one, `ignore_seen_line`,
  `update_earn_group`.
- **Branch QR beyond reading**: `put_location_qr_items` with a real list (only the stale-version refusal is tested; a
  write would change the shared test branch), `add_qr_items`, codes on a QR (`channels`, `qrLocationIds`), `join_window`,
  `holder_branch` and `join_holder_branch` (they need a Rewloy Cüzdan session, a key gets `403 CREDENTIAL_NOT_ALLOWED`),
  `extend_program_cards`.
- **`copy_program` with `overrides`** (another value) and `update_batch`'s `locationIds`, `channels`, `claimUntil`.
- **Stores**: `createShop` with the platform `rewloy`, orders with lines earning by the rules, Shopify / WooCommerce refunds.
- **`BATCH_EXPIRED` on `send_batch_link`**: needs a code whose `validUntil` has passed, and the API will not create one in
  the past; checked only offline. `PROGRAM_ARCHIVED` on `send_batch_link` is not reachable either (archiving closes the
  codes first, so `BATCH_CLOSED` answers); the test accepts both, and `create_batch` on an archived program is
  checked for `409 PROGRAM_ARCHIVED`.
- **Webhook deliveries**: a delivery to a real public https address (needs a tunnel); `test_webhook`,
  `list_webhook_deliveries`, `set_webhook_status`, and signature verification (`rewloy.webhooks`) against a live delivery.
- **Streams** (`stream`, SSE), **campaigns**, **segments**, **POS keys** (`create_api_key` kind `pos`),
  **holder (Cüzdan) sessions**, **shops/checkout codes**, **wallet downloads**: not exercised; they need other
  credentials or outside services.
- **`reset_test_environment` with a key**: keys may not call it (`403 CREDENTIAL_NOT_ALLOWED`, which the errors area
  checks). The reset runs only with `REWLOY_STAFF_TOKEN`; a business may reset five times a day.
- Other card types (points, discount, vip, voucher, cashback) beyond stamp and gift card.

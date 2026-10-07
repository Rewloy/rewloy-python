# Live tests: not covered yet (for the 0.3.0 regeneration)

The library is 0.2.4 (API 1.2.0). What the live suite cannot test because 0.2.4 does not have it, or cannot reach:

- **recordSale receipt lines** (line items): not in the 1.2.0 spec. `test_record_sale_with_receipt_lines` is a visible
  skip; fill it when 1.3.0 adds the line-item schema (the server answers `400 VALIDATION` on `lines` until then).
- **Earn rules** (groups, one line-item schema), **branch QR** (one QR per branch, curated and seasonal programmes,
  session-reuse multi-join, branch freeze): 1.3.0 operations, new areas `earn_rules` and `branch_qr`.
- **`GET /v1/meta` `environment`**: the field exists on the server but is missing from 0.2.4's `GetMetaData` type;
  the suite reads it untyped (`Any`). Once typed, drop the comment in `test_live_01_meta.py`.
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

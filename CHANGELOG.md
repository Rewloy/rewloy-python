# Değişiklik günlüğü / Changelog

Bu kütüphanenin sürümleri. API'nin kendi değişiklikleri:
https://rewloy.com/gelistiriciler/degisiklikler

This library's releases. The API's own changes are listed at the link above.

## 0.2.2 (2026-10-05)

Rewloy 1.1.0'a (API sürümü) göre yeniden üretildi: 256 işlem (0.2.1'de 255). Kasa
için `reverse_action`, `record_sale`'de `occurredAt`, `pass_action`'da
`reference`; yanıtlarda `RateLimit-*` başlıkları.

Regenerated from Rewloy 1.1.0 (the product version in `info.version`): 256
operations (255 in 0.2.1).

- **New operation: `reverse_action`** (`POST /v1/passes/{serial}/actions/reverse`,
  `reverseAction`). Voids a till action made with `pass_action` (`spend`,
  `spend-points`, `redeem-stamps`, `redeem-reward`, `use`), found by its
  `actionKey` (the `Idempotency-Key` it was sent with) or its `reference`. It
  needs no `Idempotency-Key`: an action is voided once and a repeat answers
  `duplicate: true`. New error codes `ACTION_NOT_FOUND`, `ACTION_AMBIGUOUS`,
  `ACTION_NOT_REVERSIBLE`.
- **`record_sale` takes an optional `occurredAt`**: when the sale really
  happened (ISO 8601 with offset), for a till that queues sales while offline.
- **`pass_action` takes an optional `reference`**, and its answer is now a
  `Union` of two `TypedDict`s: the balance-card answer (`balance`, `detail`,
  `promotion`) or the coupon / discount-card answer (`status`, `uses`,
  `usesLeft`). The closed members of every `oneOf` are `@final` now, so mypy and
  pyright narrow the union by `"uses" in answer` (the `final` import sits under
  `TYPE_CHECKING`: no runtime dependency).
- **Rate limit headers.** `ApiResponse.rate_limit` (`RateLimit(limit, remaining,
  reset)`, from `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`;
  `None` when the answer has none) and `RewloyError.rate_limit` (including
  `RateLimitError`). `RateLimit` and `parse_rate_limit(headers)` are exported.
  Additive.
- Webhook-creation responses may carry `warnings` (a non-live installation whose
  URL production would refuse); the `Idempotency-Key` parameter documents its
  8–64 printable ASCII rule; the API's descriptions no longer contain internal
  `ADR n` references. README: the till example has a void step and a note on
  `occurredAt` for offline queues.

## 0.2.1 (2026-10-05)

Dışarıdan geliştiricilerin bulduğu üç sorun düzeltildi.

Three problems found by outside developers, fixed.

- **`Idempotency-Key` is checked before sending.** A key with non-ASCII
  characters (`fiş-0042`) crashed the HTTP layer with a raw encoding error.
  Now the client refuses any key that is not printable ASCII (0x21–0x7E), 8–64
  characters, with a clear `ValueError` ("Idempotency-Key yalnız ASCII
  karakterler içerebilir …") and sends nothing. The API will also answer
  `400 VALIDATION` for such a key in its next release.
- **`base_url` takes the address with or without `/v1`.** The documentation and
  the OpenAPI document show `https://app.rewloy.com/v1`; the client wanted the
  origin only. Now both work; a trailing `/v1` or `/v1/` and trailing slashes
  are stripped (`rewloy.base_url` is the origin).
- **`idempotency_key` is required where the API requires it.** For
  `record_sale`, `pass_action`, `send_campaign` and `refund_shop_redemption`
  the OpenAPI document marks the header required, but the methods took it as
  optional and made up a random UUID when it was missing, which does not
  survive a restart of your app. It is now a required keyword argument of those
  methods (`TypeError` if left out; `ValueError` through `request()`), checked
  by mypy and before anything is sent. Where the header is optional
  (`issue_pass`, …) a UUID is still generated and reused on every retry.
  **Breaking for callers that relied on the generated key** (a small break,
  taken in a patch release because the old behaviour could write a sale twice).
  An empty string is no longer treated as "no key": it is refused as invalid.

## 0.2.0 (2026-10-05)

Rewloy API 1.0.5'e göre yeniden üretildi: 255 işlem (0.1.0'da 237). Kasa için
`record_sale` ve `reverse_sale`; README'de yeni bir kasa örneği, test modu ve
`base_url`.

Regenerated from Rewloy API 1.0.5: 255 operations (237 in 0.1.0).

- **New operations (18).**
  - *Till:* `record_sale` (`recordSale`, `POST /v1/passes/{serial}/sale`:
    write a completed sale to a card; the card type decides what is written)
    and `reverse_sale` (`reverseSale`, `POST /v1/passes/{serial}/sale/reverse`:
    take a refunded sale back).
  - *Checkout codes and shop connections:* `quote_checkout_code`,
    `hold_checkout_code`, `capture_checkout_order`, `release_checkout_order`,
    `refund_checkout_order`, `list_order_redemptions`, `list_shop_redemptions`,
    `release_shop_redemption`, `refund_shop_redemption`, `set_shop_settings`,
    `set_shop_ceiling`, `set_shop_plugin_abilities`, and for the card holder
    `holder_checkout_codes`, `mint_holder_checkout_code`,
    `cancel_holder_checkout_code`.
  - `get_meta` (`GET /v1/meta`): the API's version.
- **`get_pass`** now also returns `programName`, `currency`, `stamps`
  (`count`, `max`), `points`, `money` (`amountMinor`, `currency`), `customer`
  (with `customers.read`), `actions` and `sale`.
- **Webhooks.** `webhooks.manage` API keys manage webhooks (`create_webhook`,
  `list_webhooks`, `get_webhook`, `set_webhook_status`, `test_webhook`,
  `list_webhook_deliveries`, `webhook_events`); a webhook reports
  `createdByKey`.
- **Other fields.** `issue_pass` returns `created`; business lists and `me`
  carry `currency`; programs carry `sale`; batches `onlineValue`; shops
  `accepts`, `settings`, `shopName`, `unbacked` and the plugin key's
  `abilities`.
- **Tests.** The operation count is read from the snapshot instead of being
  hard-coded (237), which is what failed the Regenerate check.
- **README.**
  - A till example with `record_sale`, the structured fields of `get_pass`
    and a refund with `reverse_sale`.
  - `Idempotency-Key`: a key is unique for good per credential. The
    receipt number alone is not a key (fiscal receipt numbers restart after
    the Z report): use register + Z number + receipt number, or a UUID
    stored with the sale. The receipt number goes in `reference`.
  - Test mode exists: `rwk_test_` keys and a test business. The "being
    prepared" wording is gone.
  - How to set a custom base URL (staging), and a link to the developer
    docs, https://rewloy.com/gelistiriciler.

## 0.1.0 (2026-10-04)

İlk önizleme. Rewloy API 1.0.0'a göre üretildi (4 Ekim 2026): 195 yol,
237 işlem.

First preview, generated from Rewloy API 1.0.0 as of 4 Oct 2026 (195 paths,
237 operations):

- **Client.** `Rewloy(api_key=…)`, `Rewloy(staff_session=…, merchant=…)` or
  `Rewloy(holder_session=…)`, with `base_url`, `timeout`, `max_retries`,
  `transport`, `user_agent` and `sleep`. Python 3.9 and later, no runtime
  dependencies, thread-safe, synchronous.
- **Methods.** One method per operation, named by its operationId in
  snake_case, typed with `TypedDict`s from the OpenAPI document
  (`rewloy.types`); `METHOD_NAMES` and `OPERATION_IDS` map the names.
  `request()` returns the whole answer (`status`, `request_id`, `mode`,
  `replayed`). `mypy --strict` passes.
- **Retries** on network errors, timeouts, 429, 502–504 and 520–524, with
  exponential backoff, jitter and `Retry-After`. Only safe requests are
  retried; the timeout covers a whole attempt.
- **`Idempotency-Key`** for till actions, campaigns and card issue: generated
  when omitted, reused across retries.
- **Pagination** with `paginate()`, typed per list.
- **Server-sent events** with `stream()`, `live_feed()` and
  `holder_card_events()`, with reconnection and `Last-Event-ID`; closed by
  `break`, `with` or `close()`.
- **Webhooks:** `verify_webhook()` and `sign_webhook()`.
- **Errors:** `RewloyError`, `RateLimitError`, `RewloyConnectionError` and
  `RewloyTimeoutError`.
- **Deprecations:** one `DeprecationWarning` per deprecated operation,
  attributed to the caller's line.
- **Transports:** the default one on `urllib` (no redirects, no dependency),
  an optional one on `httpx` (`pip install "rewloy[httpx]"`), and any object
  with `send`, `open_stream` and `close`.
- **Regeneration:** `python scripts/generate.py`, plus a daily workflow that
  opens a pull request when the live document changes.

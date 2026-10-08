# Değişiklik günlüğü / Changelog

Bu kütüphanenin sürümleri. API'nin kendi değişiklikleri:
https://rewloy.com/gelistiriciler/degisiklikler

This library's releases. The API's own changes are listed at the link above.

## 0.3.0 (2026-10-07)

Rewloy API 1.3.2'yi izler (API sürümü, `info.version`; çekirdek etiketi v1.3.2): 298 işlem
(0.2.4'te 260), hiçbiri kaldırılmadı. Kazanım kuralları (ürün grupları, kurallar, önizleme),
fiş satırlı satış ve satır iadesi, şube QR'ı (herkese açık sayfa, görüntü ve
baskı, QR listesi), şube dondurma, kodu düzenleme, kartın kopyası ve kartları
uzatma; yeni webhook olayları (`pass.extended`, `location.frozen`,
`location.unfrozen`, `business.paused`, `business.resumed`) ve 31 yeni hata
kodu (`LOCATION_FROZEN`, `BUSINESS_FROZEN`, `REVISION_CONFLICT`, `TOO_MANY_LINES`
ve öbürleri); `NOT_AN_INSTRUMENT` artık `copyProgram`da da döner.
Beş kütüphane 0.3.0'da aynı sürüme gelir. Ayrıca `pytest -m live` (README,
"Canlı testler / Live tests") kütüphaneyi bir Rewloy DEV sunucusuna karşı çalıştırır.

Follows Rewloy API 1.3.2 (the product version in `info.version`; core tag
v1.3.2): 298 operations (260 in 0.2.4), none removed, and 37 new error codes
(the six that 1.3.2 added to the document's enum, `DPA_DRAFT`, `SUMMARY_REQUIRED`,
`PREVIEW_CHANGED`, `DAY_CHANGED`, `NOTHING_TO_SEND` and `NOTICE_TOO_LATE`, are
console-only codes that `/v1` never returns). All five client
libraries are 0.3.0.
Additive: every 0.2.4 method keeps its name, its parameters and its meaning
(new keyword arguments are optional). The one change that a type checker can
see in existing code is in the webhook types (see "Typing note" below).

- **Earn rules** (38 new operations in all; the others below). A program's earn
  now follows product groups: `createEarnGroup`, `listEarnGroups`,
  `getEarnGroup`, `updateEarnGroup`, `deleteEarnGroup` (`409 GROUP_IN_USE`
  while a rule uses it), the categories and products the tills have sent
  (`listSeenLines`, `ignoreSeenLine`, `unignoreSeenLine`, `listEarnSources`),
  ready-made rule sets (`listEarnTemplates`) and the rules themselves:
  `getEarnRules`, `putEarnRules` (the whole set, with the `revision` you read:
  `409 REVISION_CONFLICT`), `createEarnRule`, `updateEarnRule`,
  `deleteEarnRule`, `deleteEarnRules`, `listEarnRuleRevisions`. Rule kinds:
  `stamp.perUnit`, `stamp.perLine`, `stamp.perReceipt`, `points.rate`,
  `points.multiplier`, `cashback.rate`, `cashback.groupRate`, `vip.visit`;
  `settings` hold the excluded groups, the receipt minimum, the receipt / day /
  month caps, `noLines`, `countLoyaltyPaid`, `spendShareMaxPct`,
  `unitPriceBasis`, `capsAfterPromotion` and `restrictedGoods`. New errors:
  `RULE_KIND_NOT_FOR_TYPE`, `EARN_RULE_NOT_FOUND`, `EARN_RULES_NOT_FOUND`,
  `BILL_REQUIRED` and `SPEND_SHARE_EXCEEDED` (cashback paid for a share of a
  bill; `passAction` `spend` takes the new `billMinor`).
- **Receipt lines on a sale.** `recordSale` takes `lines` (up to 500: `lineId`,
  `name`, `unitPriceMinor`, `quantity`, `unit`, `sku`, `category`,
  `discountMinor`, `totalMinor`, `kind`, `tags`) and `receiptDiscountMinor`.
  The answer of a sale sent with lines carries `earn`: what each line earned
  (`status`, `groups`, `rules`, `earned`), what each rule did and the total step
  by step (`beforeRounding`, `receiptCap`, `promotion`, `caps`, `credited`).
  `reason` has new values (`no_earning_lines`, `no_lines`, `location_frozen`,
  `business_paused`, …). New errors, only when lines are sent: `TOO_MANY_LINES`,
  `LINE_AMOUNT_INVALID`, `LINES_TOTAL_MISMATCH`. A sale without lines, and a
  program without rules, earn as before.
- **New operation `previewSale`** (`POST /v1/passes/{serial}/sale/preview`):
  the body of `recordSale`, the answer of `recordSale` with `preview: true`,
  nothing written, no `Idempotency-Key`. **New operation `previewEarn`**
  (`POST /v1/programs/{id}/earn-rules/preview`): what a receipt would earn
  without a card, with unsaved draft rules (`ruleSet`), a branch's till
  campaign (`locationId`), an earlier moment (`occurredAt`) and a card's state
  (`context`).
- **Line refunds.** `reverseSale` takes `lines: [{lineId, quantity?, amountMinor?}]`
  (needs an `Idempotency-Key`): the sale is judged again with the remaining
  lines and only the difference is taken back (`reversed` may be 0). The answer
  carries `earn` and `linesLeft`; new errors `LINE_NOT_FOUND` and
  `LINE_ALREADY_REFUNDED`. `reverse_sale` now takes `idempotency_key=` (the key
  of the refund; required with `lines`, optional without).
- **Branch QR.** Every branch has a permanent QR: `Location.qr` (`code`, `url`,
  `state`), `stats.qrCards30`. `publicBranch` (`GET /v1/public/branches/{code}`,
  no credentials), `holderBranch` and `joinHolderBranch` (a Rewloy Cüzdan
  session), the images and the print sheet (`locationQrSvg`, `locationQrPng`,
  `locationQrSheetPdf`, `locationQrSheetSvg`, returned as `bytes`), the QR list
  (`getLocationQrItems`, `putLocationQrItems` with the `version` you read:
  `409 QR_LIST_CHANGED`, `addQrItems`, `previewLocationQr`). Codes can sit on a
  branch QR (`channels`, `qrLocationIds`, `claimFrom` / `claimUntil`,
  `proofRequired` on `createBatch`); `joinWindow` on a program; new errors
  `BRANCH_NOT_FOUND`, `BRANCH_GONE`, `ITEM_NOT_OFFERED`, `PROOF_REQUIRED`,
  `QR_ITEM_INVALID`, `NOT_VALID_HERE`, `BATCH_CAP_REQUIRED`,
  `BATCH_PER_PERSON_REQUIRED`, `CLAIM_AFTER_CARD_END`,
  `CAPACITY_BELOW_CLAIMED`.
- **Branch freeze.** `freezeLocation`, `updateLocationFreeze`,
  `cancelLocationFreeze`, `unfreezeLocation`, `listLocationFreezes`;
  `Location.frozen`. Freezing needs a team session and the person's password: a
  key gets `403 CREDENTIAL_NOT_ALLOWED`. A frozen branch's till answers
  `409 LOCATION_FROZEN` (`getPassTill` says `allowed: false` and `frozen`), a
  business whose every branch is frozen `BUSINESS_FROZEN`; reversals of earlier
  operations still work. Also `ALREADY_FROZEN`, `NOT_FROZEN`, `LOCATION_ARCHIVED`,
  `FREEZE_LIMIT`, `FREEZE_STARTED`. `getPlan` has `billing.days`.
- **Codes and cards.** New `updateBatch` (`PATCH /v1/batches/{id}`: `name`,
  `claimUntil`, `capacity`, `perPerson`, `locationIds`, `channels`,
  `qrLocationIds`), `copyProgram` (`POST /v1/programs/{id}/copy`: a gift card,
  coupon or discount card with another value; a loyalty card is refused with
  `422 NOT_AN_INSTRUMENT`), `extendProgramCards` (`POST /v1/programs/{id}/extend`).
  A program's terms are now fields (`giftValueMinor`, `offerValueMinor`,
  `usage`, `validity`, `terms`), each card keeps the terms of the day it was
  taken, and `listAllBatches` rows have the state `scheduled`.
- **Webhook events.** `pass.extended` (a card's end moved later: `reason`
  `merchant` or `branch_frozen`, `from`, `to`), `location.frozen`,
  `location.unfrozen`, `business.paused`, `business.resumed` (not about a card:
  `card` and `customer_id` are null); `partial: true` on the `pass.activity`
  `adjust` event of a line refund. Existing webhooks do not receive them unless
  they select them.
- **Smaller:** `getMeta` is typed with `environment` (`live` | `dev`); stores:
  `createShop` accepts the platform `rewloy`, orders with lines earn by the
  rules, `lastDelivery.result` has new values; `getHolderData` carries
  `receipts`, `holderCard` carries `notices`; `programJoinQr` takes `branchCode`
  and `format`; `joinHolderProgram` and `claimHolderCode` take `branchCode`;
  `createLocation` takes `qrListFrom` and `programIds`; the notification kind
  `branch`.
- **Typing note (the only visible change in existing code).** `WebhookEvent` is
  now `PassEvent | BranchEvent | WebhookTestEvent` and `PassEvent.type` includes
  `pass.extended`. A handler that narrowed with only `event["type"] == "webhook.test"`
  and then read `event["data"]["unit"]` must also narrow on the type
  (`event["type"] == "pass.activity"`) for `mypy`; nothing changes at run time.
  `PassEventData` gained `reference`, `occurredAt`, `undone` and `partial`.
  New exports: `BranchEvent`, `BranchEventData`, `PassExtendedData`.
- Python: the new tests are `tests/test_v130.py` (the operations and errors, a
  group, rules and previews, lines on a sale and the `earn` explanation, a line
  refund, binary downloads, the refusals) and one for the 1.3.0 webhook events.
  The live suite (`pytest -m live`, README) gained two areas, `earn` (a group,
  saved rules and a stale revision, `preview_earn` with and without a draft,
  `preview_sale`, a sale with lines and its `earn`, a line refund and its
  refusals, `TOO_MANY_LINES`) and `branch_qr` (a branch's public page, the
  images and the sheet, the QR list, the freeze refusals for a key,
  `copy_program`), plus `update_batch` and the 1.3.0 webhook events. Not
  covered: [tests/live/TODO.md](tests/live/TODO.md).

## 0.2.4 (2026-10-06)

Rewloy API 1.2.0'ı izler (API sürümü, `info.version`): 260 işlem (0.2.2'de 256),
hiçbiri kaldırılmadı. Kasa yazımlarının yanıtında `card`, kartın işlem listesi,
webhook sırrını yenileme ve silme, POS anahtarları, test ortamını silmeden
sıfırlama, bütün kodların listesi. Webhook nesnesinde `pausedUntil` ve
`resumableUntil`; kod bağlantısı göndermede `BATCH_CLOSED`, `BATCH_EXPIRED`,
`BATCH_FULL` ve `PROGRAM_ARCHIVED` hataları. Ayrıca README'deki `rewardReady`
örneği `actions[].ready` okuyacak şekilde düzeltildi. 0.2.3 yalnız .NET ve
Kotlin'in paket sürümüydü; beş kütüphane 0.2.4'te aynı sürüme gelir.

Follows Rewloy API 1.2.0 (the product version in `info.version`): 260
operations (256 in 0.2.2), none removed. All five client libraries are 0.2.4.
Additive, except that `closed` in the test-reset answer is now always `null`
and `sendBatchLink` now refuses a code that issues no card (see below).

- **New operation `listPassOperations`** (`GET /v1/passes/{serial}/operations`,
  paged): a card's ledger operations and coupon / discount-card uses, newest
  first, for a till's "last operations" list. Each carries `kind`, signed
  `delta` and `unit`, `at` (and `occurredAt` for a sale written later),
  `reference`, `source`, `byCaller`, and what undoes it: `undoWith`
  (`sale/reverse` or `actions/reverse`), `reversible` and, when not,
  `reason`; for this credential's own operations `saleKey` / `actionKey` to pass
  straight to the reverse call; `reversedBy`, `reversedAt`, `reverses`.
  Needs `passes.read`.
- **`card` on write answers** (`recordSale`, `passAction`, `reverseSale`,
  `reverseAction`): the card after the write, the fields of `getPass` except
  `customer` (`programName`, `currency`, `stamps` / `points` / `money`,
  `rewardReady`, `actions`, `sale`…), read in the same transaction. On a replay
  (`duplicate: true`) it is the card's current state. It is `null` when the
  credential lacks `passes.read` in the card's programme (a till-only plugin
  key), so the type is nullable. No second `getPass` is needed to draw a receipt.
- **`reversed` on `recordSale` and `passAction` answers**: `true` only on a
  replay of a sale that was taken back since (`credited` is what the first
  request wrote, the card no longer carries it); send a new key to write the
  receipt again.
- **`occurredAt` errors**: a rejected `occurredAt` is a `400 VALIDATION` whose
  `details[0].reason` says which limit: `in_future`, `too_old` (over 72 hours),
  `before_issue` (the card did not exist then: resend without `occurredAt`),
  `invalid`. Treat an unknown reason as `invalid`. (Documented on the error
  details; the field stays optional.)
- **New operations `rotateWebhookSecret`** (`POST /v1/developers/webhooks/{id}/rotate-secret`)
  and **`deleteWebhook`** (`DELETE /v1/developers/webhooks/{id}`, `204`). A
  rotation returns the new `secret` once; the old one keeps signing for 24
  hours, so `Rewloy-Signature` carries two `v1` values and the delivery has
  `Rewloy-Signature-Rotating: 1`. `verifyWebhook` already tried every `v1` and
  several secrets: pass `[new, old]` while you switch. Deleting removes the
  delivery history too.
- **POS keys**: `createApiKey` takes a second body shape, `kind: "pos"` with
  `locationId` and optional `register` (the built-in till role, one branch, named
  "POS · branch · register"), and answers with `baseUrl`; `listApiKeys` and
  `getApiKey` rows carry `pos` (`{ locationId, register } | null`) and
  `requestsToday`, and `listApiKeys` filters with `kind` (`pos` | `standard`).
- **Test environment reset** (`resetTestEnvironment`) keeps the test business: the
  body takes `revokeKeys` (default `false`; `true` also revokes the keys, closes
  the webhooks and cancels open store-link codes), and the answer counts
  `deleted` (`customers`, `cards`, `codes`, `outbox`, `webhookDeliveries`), `kept`
  (`programs`, `keys`, `webhooks`), `created`, `keysRevoked` and
  `walletCardsVoided`; `closed` is now always `null`. New error code
  `TEST_RESET_BUSY` (`409`).
- **New operation `listAllBatches`** (`GET /v1/batches`, paged): every gift-card,
  coupon and discount code of the business, newest first; filters `programId`,
  `type`, `status` and `q`. Each row's `state` (and the `status` filter) takes
  **`archived`**: the code itself is open but its card (programme) is archived,
  so its link issues nothing; `status` on the row stays `open` | `closed`. New error
  code `PROGRAM_ARCHIVED` (`409`) on `createBatch` for an archived programme.
- **Programme rows** (`listPrograms`, `getProgram`, `createProgram`,
  `updateProgram`) carry `programName`, always equal to `name` (the field name
  that `createProgram` takes and `getPass` returns).
- **Webhook state: `pausedUntil` and `resumableUntil`** on every webhook object
  (the rows of `listWebhooks`, and the `webhook` of `createWebhook`, `getWebhook`,
  `setWebhookStatus` and `rotateWebhookSecret`). Both are always present, a
  date-time or `null`. `pausedUntil`: an open webhook is paused (its receiver
  failed twice in a row with a `5xx`, a `429`, a connection error or no answer):
  its deliveries wait until this moment and are retried on their own, 60
  seconds; `null` when it is not paused or the webhook is off.
  `resumableUntil`: the rules turned the webhook off and keep its pending
  deliveries; turned on before this moment (24 hours after it was closed, with
  `setWebhookStatus` `{ "active": true }`) it carries on where it stopped, the
  kept deliveries go at once and the events that happened meanwhile arrive too;
  `null` while it is on, when a person or a key turned it off, or once the time
  has passed.
- **`sendBatchLink` refusals** (`POST /v1/batches/{id}/send`): the link of a code
  is e-mailed only while the code issues a card. A stopped code answers
  `410 BATCH_CLOSED`, one past its date `410 BATCH_EXPIRED`, one whose cards
  are all given `410 BATCH_FULL`, and a code whose programme is archived
  `409 PROGRAM_ARCHIVED` (a new `409` on this operation); no mail goes. Before
  1.2.0 the last three were sent anyway. The error codes were already in the
  library's list of codes; the operation's description now names all four.
- Descriptions only: `earnRate` / `cashbackRate` round down on a sale
  (`floor(amountMinor / 100 × earnRate)`, `floor(amountMinor × cashbackRate / 100)`);
  `currencyLocked` also for an open amount-valued coupon; `actions30` on a key
  now counts reads; `rewardReady` means "reward ready" only on stamp and points
  cards (always `true` on VIP, any balance on cashback and gift cards): read
  `actions[].ready` to know what can be done now; `kvkkConsent` on `issuePass`;
  `me` → `key.abilities` is not the key's permissions (those are `permissions`).
- **Fixed in the README**: the first example read `rewardReady` as "ready to
  redeem". It now reads `actions[].ready` (see `getPass`).
- Python: `pausedUntil` and `resumableUntil` are `Optional[str]` keys of the
  webhook `TypedDict`s (`list_webhooks`, `create_webhook`, `get_webhook`,
  `set_webhook_status`, `rotate_webhook_secret`); the `send_batch_link`
  docstring names the four refusals, and the codes are in `rewloy.types.ErrorCode`.
- Python: new tests in `tests/test_v120.py` (the four new operations, paging,
  `kind: "pos"`, `revokeKeys`, a replayed sale with `card: None`,
  `PROGRAM_ARCHIVED`, the webhook state fields, the four refusals of
  `send_batch_link`); `RewloyError.details` documents `reason`. The
  `# type: ignore` in a retry test now also silences mypy's
  `comparison-overlap` (the typed answer has more required fields).

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

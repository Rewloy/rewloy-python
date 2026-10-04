# Değişiklik günlüğü / Changelog

Bu kütüphanenin sürümleri. API'nin kendi değişiklikleri:
https://rewloy.com/gelistiriciler/degisiklikler

This library's releases. The API's own changes are listed at the link above.

## 0.1.0 (yayımlanmadı / unreleased)

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

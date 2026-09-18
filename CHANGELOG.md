# Changelog

## 0.2.0 — 2026-09-19

**Jupiter API migration — legacy hosts retired.** Jupiter killed the old V6 host
(`quote-api.jup.ag`) and the Token v1 host (`tokens.jup.ag`); both now fail to
resolve. This release moves the client to Jupiter's current API surface:

- **Swap API:** the default base URL is now `https://lite-api.jup.ag/swap/v1`
  (keyless). When an `api_key` is supplied, the keyed endpoint
  `https://api.jup.ag/swap/v1` is used automatically. The constructor gained a
  `swap_url=` argument; the old `v6_url=` argument is kept as a deprecated alias.
  Request/response shapes are unchanged (drop-in).
- **Ultra API:** `ultra_order()` now uses `GET /order` with query parameters —
  the legacy POST-body form returns HTTP 404. Orders that come back HTTP 200
  with an `error` field (e.g. `Insufficient funds`) now raise `JupiterError`
  instead of silently returning an empty transaction. `ultra_execute()` is
  unchanged (`POST /execute`).
- **Token API:** migrated to `/tokens/v2`. `get_token_info()` uses
  `search?query=<mint>` and matches the id exactly; `get_strict_list()` returns
  the `verified` tag list (v2 removed the dedicated `strict` endpoint — strict
  entries still carry a `strict` tag in `TokenInfo.tags`). Jupiter removed the
  public banned list in v2, so `is_banned()` now returns `False` unless a list
  is ever served; it degrades gracefully instead of erroring.
- **Docs:** API-key portal link updated to `developers.jup.ag`.

## 0.1.1 — 2026-05-29

- mypy strict + ruff clean; PyPI release via GitHub Actions Trusted Publishing on a version tag.

## 0.1.0

- Initial release
- Jupiter V6 quote and swap API
- Jupiter Ultra API (combined quote + swap with MEV protection)
- Jupiter Token API (metadata, verification, banned detection)
- Async/await with `httpx`
- Built-in rate limiting and 429 retry
- Fully typed with `py.typed` marker

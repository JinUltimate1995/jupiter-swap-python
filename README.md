# jupiter-swap-python

**The missing Jupiter swap client for Python. Async. Typed. Production-tested.**

[![PyPI version](https://img.shields.io/pypi/v/jupiter-swap-python?color=blue)](https://pypi.org/project/jupiter-swap-python/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/JinUltimate1995/jupiter-swap-python/actions/workflows/ci.yml/badge.svg)](https://github.com/JinUltimate1995/jupiter-swap-python/actions)

Jupiter's own Python SDK was abandoned (returns 404). This library fills the gap — a clean, typed, async client for [Jupiter](https://jup.ag), the #1 DEX aggregator on Solana.

---

## ⚡ Quickstart

```bash
pip install jupiter-swap-python
```

### Get a quote

```python
import asyncio
from jupiter_swap import JupiterClient

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

async def main():
    async with JupiterClient() as jup:
        quote = await jup.get_quote(SOL, USDC, 1_000_000_000)  # 1 SOL
        print(f"1 SOL = {int(quote.out_amount) / 1e6:.2f} USDC")
        print(f"Price impact: {quote.price_impact_pct}%")

asyncio.run(main())
```

### Swap tokens

```python
async with JupiterClient(api_key="your-key") as jup:
    # Step 1: Get quote
    quote = await jup.get_quote(SOL, USDC, 1_000_000_000)

    # Step 2: Build swap transaction
    swap = await jup.get_swap_transaction(
        quote,
        user_public_key="YourWalletPublicKey...",
        priority_fee_lamports=500_000,  # 0.0005 SOL
    )

    # Step 3: Sign and send swap.swap_transaction with your wallet
    print(f"Transaction ready (block height: {swap.last_valid_block_height})")
```

### Ultra API (recommended for production)

```python
async with JupiterClient(api_key="your-key") as jup:
    # Combined quote + swap in one call
    order = await jup.ultra_order(
        input_mint=SOL,
        output_mint=USDC,
        amount=1_000_000_000,
        taker="YourWalletPublicKey...",
    )

    print(f"Swap type: {order.swap_type}")
    print(f"Out amount: {order.out_amount}")

    # Sign order.swap_transaction with your wallet, then:
    tx_sig = await jup.ultra_execute(signed_transaction, order.request_id)
    print(f"Executed: {tx_sig}")
```

### Token verification

```python
from jupiter_swap import TokenClient

async with TokenClient() as tokens:
    info = await tokens.get_token_info("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    print(f"{info.symbol} — verified: {info.is_verified}, banned: {info.is_banned}")

    # Check if a token is a known scam
    if await tokens.is_banned("SomeScamMint..."):
        print("🚫 Token is banned!")
```

---

## 🔧 API Reference

### `JupiterClient`

| Method | Description |
|--------|-------------|
| `get_quote()` | Get the best swap route and price |
| `get_swap_transaction()` | Build a signable transaction from a quote |
| `ultra_order()` | Combined quote + swap via Ultra API (MEV protection) |
| `ultra_execute()` | Execute a signed Ultra swap order |

### `TokenClient`

| Method | Description |
|--------|-------------|
| `get_token_info()` | Get token metadata and verification status |
| `is_banned()` | Check if a token is on the banned list |
| `is_verified()` | Check if a token is verified |
| `get_strict_list()` | Get all strictly verified tokens |
| `refresh_banned_list()` | Manually refresh the banned list |

### Models

- `QuoteResponse` — Route details, expected output, price impact
- `SwapResponse` — Base64 transaction ready to sign
- `UltraOrder` — Combined quote + transaction from Ultra API
- `TokenInfo` — Name, symbol, decimals, verification flags

---

## 🛡️ Why this library?

| Problem | Solution |
|---------|----------|
| Jupiter's Python SDK is deleted | This exists |
| Raw `httpx.post()` calls everywhere | Typed client with proper models |
| No 429 handling | Built-in retry with exponential backoff |
| Token safety is an afterthought | `TokenClient` with banned/verified checks |
| Sync-only clients | Fully async with `httpx` |

---

## 🔑 API Key

A Jupiter API key is optional but recommended for production use (higher rate limits).

Get one at [station.jup.ag](https://station.jup.ag/).

```python
client = JupiterClient(api_key="your-api-key")
```

---

## 📦 Also by JinUltimate1995

- [**solana-rpc-resilient**](https://github.com/JinUltimate1995/solana-rpc-resilient) — Solana RPC client with automatic failover, rate limiting, and circuit breaker
- [**dexscreener-python**](https://github.com/JinUltimate1995/dexscreener-python) — Async DexScreener API client for token/pair data across 80+ chains

---

## License

MIT

---

## Support

If this saved you time, a tip is appreciated — it funds maintenance.

**Tip jar (SOL):** `Evot66rHqu6WyiBF948YipgArHSMeJ5D4GeNJXPTpV6q`

You can also sponsor via the GitHub **Sponsor** button.

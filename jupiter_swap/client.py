"""
Jupiter DEX aggregator client — Swap API quote/swap and Ultra API.

Supports:
- Quote: get the best swap route and price
- Swap: build a transaction from a quote
- Ultra: combined quote + swap with MEV protection

API endpoints (2026 surface):
- Swap API (keyless): ``https://lite-api.jup.ag/swap/v1`` (formerly "V6" at quote-api.jup.ag)
- Swap API (keyed):   ``https://api.jup.ag/swap/v1``
- Ultra API:          ``https://api.jup.ag/ultra/v1``
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any, cast

import httpx

from .models import QuoteResponse, SwapResponse, UltraOrder

logger = logging.getLogger(__name__)

# Jupiter public API base URLs
_DEFAULT_SWAP_URL = "https://lite-api.jup.ag/swap/v1"
_KEYED_SWAP_URL = "https://api.jup.ag/swap/v1"
_DEFAULT_ULTRA_URL = "https://api.jup.ag/ultra/v1"


class JupiterError(Exception):
    """Raised when a Jupiter API call fails."""

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class JupiterClient:
    """
    Async client for the Jupiter DEX aggregator.

    Usage::

        async with JupiterClient() as jup:
            quote = await jup.get_quote("So11...", "EPjFW...", 1_000_000)
            swap = await jup.get_swap_transaction(quote, "YourPublicKey...")

    Handles 429 rate limiting with automatic retry and exponential backoff.
    """

    __slots__ = (
        "_swap_url",
        "_ultra_url",
        "_api_key",
        "_http",
        "_max_retries",
        "_last_request_time",
        "_min_interval",
    )

    def __init__(
        self,
        *,
        api_key: str = "",
        swap_url: str | None = None,
        v6_url: str | None = None,
        ultra_url: str = _DEFAULT_ULTRA_URL,
        max_retries: int = 3,
        requests_per_second: float = 10.0,
    ) -> None:
        """
        Initialise the Jupiter client.

        Args:
            api_key: Optional Jupiter API key for higher rate limits. When set,
                the keyed endpoint (``api.jup.ag``) is used by default.
            swap_url: Base URL for the Swap API. Defaults to
                ``lite-api.jup.ag/swap/v1`` (keyless), or ``api.jup.ag/swap/v1``
                when ``api_key`` is supplied.
            v6_url: Deprecated alias for ``swap_url`` (Jupiter's legacy "V6"
                base URL). Prefer ``swap_url``.
            ultra_url: Base URL for the Ultra swap API.
            max_retries: Max retry attempts on 429 responses.
            requests_per_second: Simple rate limiter — minimum interval between requests.
        """
        if swap_url is None:
            swap_url = v6_url
        if swap_url is None:
            swap_url = _KEYED_SWAP_URL if api_key else _DEFAULT_SWAP_URL
        self._swap_url = swap_url.rstrip("/")
        self._ultra_url = ultra_url.rstrip("/")
        self._api_key = api_key
        self._http: httpx.AsyncClient | None = None
        self._max_retries = max_retries
        self._last_request_time: float = 0.0
        self._min_interval: float = 1.0 / requests_per_second if requests_per_second > 0 else 0.0

    # -- Lifecycle -----------------------------------------------------------

    async def __aenter__(self) -> JupiterClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the HTTP connection pool."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def close(self) -> None:
        """Close the HTTP connection pool."""
        if self._http:
            await self._http.aclose()
            self._http = None

    # -- Swap API (quote / swap) ---------------------------------------------

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
        *,
        swap_mode: str = "ExactIn",
        restrict_intermediate_tokens: bool = True,
        max_accounts: int = 64,
    ) -> QuoteResponse:
        """
        Get the best swap route from Jupiter.

        Args:
            input_mint: Source token mint address.
            output_mint: Destination token mint address.
            amount: Amount in smallest unit (lamports for SOL).
            slippage_bps: Maximum slippage in basis points (1 bps = 0.01%).
            swap_mode: "ExactIn" or "ExactOut".
            restrict_intermediate_tokens: Avoid illiquid intermediate hops.
            max_accounts: Max accounts in the route (higher = more complex routes).

        Returns:
            QuoteResponse with route details and expected output amount.

        Raises:
            JupiterError: If the quote request fails.
        """
        params: dict[str, str | int] = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
            "swapMode": swap_mode,
        }
        if restrict_intermediate_tokens:
            params["restrictIntermediateTokens"] = "true"
        if max_accounts != 64:
            params["maxAccounts"] = str(max_accounts)

        data = await self._request("GET", f"{self._swap_url}/quote", params=params)

        return QuoteResponse(
            input_mint=data.get("inputMint", input_mint),
            output_mint=data.get("outputMint", output_mint),
            in_amount=data.get("inAmount", str(amount)),
            out_amount=data.get("outAmount", "0"),
            price_impact_pct=data.get("priceImpactPct", "0"),
            route_plan=data.get("routePlan", []),
            other_amount_threshold=data.get("otherAmountThreshold", "0"),
            swap_mode=data.get("swapMode", swap_mode),
            slippage_bps=data.get("slippageBps", slippage_bps),
            raw=data,
        )

    async def get_swap_transaction(
        self,
        quote: QuoteResponse,
        user_public_key: str,
        *,
        wrap_and_unwrap_sol: bool = True,
        priority_fee_lamports: int = 0,
        dynamic_compute_unit_limit: bool = True,
        priority_level: str = "veryHigh",
    ) -> SwapResponse:
        """
        Build a swap transaction from a quote.

        Args:
            quote: A QuoteResponse from get_quote().
            user_public_key: The wallet public key that will sign the tx.
            wrap_and_unwrap_sol: Auto wrap/unwrap SOL ↔ WSOL.
            priority_fee_lamports: Max priority fee in lamports (0 = use default).
            dynamic_compute_unit_limit: Auto-optimize compute unit limit.
            priority_level: Priority level — "medium", "high", "veryHigh".

        Returns:
            SwapResponse with the base64-encoded transaction.

        Raises:
            JupiterError: If the swap request fails.
        """
        max_fee = priority_fee_lamports if priority_fee_lamports > 0 else 1_000_000

        body: dict[str, Any] = {
            "quoteResponse": quote.raw,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": wrap_and_unwrap_sol,
            "dynamicComputeUnitLimit": dynamic_compute_unit_limit,
            "dynamicSlippage": True,
            "prioritizationFeeLamports": {
                "priorityLevelWithMaxLamports": {
                    "maxLamports": max_fee,
                    "priorityLevel": priority_level,
                },
            },
        }

        data = await self._request("POST", f"{self._swap_url}/swap", json=body)

        return SwapResponse(
            swap_transaction=data.get("swapTransaction", ""),
            last_valid_block_height=data.get("lastValidBlockHeight", 0),
            priority_fee_lamports=data.get("prioritizationFeeLamports", 0),
            raw=data,
        )

    # -- Ultra API -----------------------------------------------------------

    async def ultra_order(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        taker: str,
        slippage_bps: int = 50,
    ) -> UltraOrder:
        """
        Request a swap via Jupiter Ultra API (combined quote + swap).

        Ultra provides:
        - Built-in MEV protection
        - Automatic priority fee optimisation
        - Better routing engine
        - Gasless mode support

        Args:
            input_mint: Source token mint address.
            output_mint: Destination token mint address.
            amount: Amount in smallest unit.
            taker: Wallet public key of the swap taker.
            slippage_bps: Maximum slippage in basis points.

        Returns:
            UltraOrder with a transaction ready to sign and execute.

        Raises:
            JupiterError: If the order request fails, or the order reports a
                business error (e.g. "Insufficient funds", "No route found").
        """
        params: dict[str, str | int] = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "taker": taker,
            "slippageBps": slippage_bps,
        }

        data = await self._request("GET", f"{self._ultra_url}/order", params=params)

        # Ultra answers HTTP 200 with an `error` field for business errors.
        # Surface those instead of silently returning an empty transaction.
        if data.get("error"):
            message = data.get("errorMessage") or data.get("error")
            raise JupiterError(f"Ultra order rejected: {message}", body=str(data)[:500])

        dynamic_slippage_bps = slippage_bps
        slip_raw = data.get("slippageBps")
        if slip_raw is None:
            report = data.get("dynamicSlippageReport") or {}
            slip_raw = report.get("slippageBps") if isinstance(report, dict) else None
        if isinstance(slip_raw, (int, float, str)):
            with contextlib.suppress(TypeError, ValueError):
                dynamic_slippage_bps = int(float(slip_raw))

        return UltraOrder(
            request_id=data.get("requestId", ""),
            input_mint=data.get("inputMint", input_mint),
            output_mint=data.get("outputMint", output_mint),
            in_amount=data.get("inAmount", str(amount)),
            out_amount=data.get("outAmount", "0"),
            swap_transaction=data.get("transaction", ""),
            swap_type=data.get("swapType", data.get("type", "swap")),
            priority_fee_lamports=data.get("prioritizationFeeLamports", 0),
            dynamic_slippage_bps=dynamic_slippage_bps,
            raw=data,
        )

    async def ultra_execute(
        self,
        signed_transaction: str,
        request_id: str,
    ) -> str:
        """
        Execute a signed Ultra swap order.

        Submit the signed transaction back to Jupiter Ultra for
        execution with MEV protection and confirmation tracking.

        Args:
            signed_transaction: Base64-encoded signed transaction.
            request_id: The request_id from the UltraOrder.

        Returns:
            Transaction signature string.

        Raises:
            JupiterError: If execution fails.
        """
        body = {
            "signedTransaction": signed_transaction,
            "requestId": request_id,
        }

        data = await self._request("POST", f"{self._ultra_url}/execute", json=body)

        status = data.get("status", "")
        tx_sig = data.get("signature", "")

        if status == "Failed":
            raise JupiterError(
                f"Ultra swap execution failed: {data.get('error', 'unknown')}",
            )

        return tx_sig if isinstance(tx_sig, str) else ""

    # -- Internal ------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if self._api_key:
            return {"x-api-key": self._api_key}
        return {}

    async def _rate_limit(self) -> None:
        """Simple rate limiter — ensure minimum interval between requests."""
        if self._min_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make an HTTP request with rate limiting and 429 retry.

        Returns parsed JSON dict on success.
        Raises JupiterError on failure.
        """
        if self._http is None:
            raise JupiterError("Client not connected — call connect() or use async with")

        await self._rate_limit()

        last_status = 0
        last_body = ""

        for attempt in range(self._max_retries + 1):
            try:
                if method == "GET":
                    resp = await self._http.get(url, params=params, headers=self._auth_headers())
                else:
                    resp = await self._http.post(url, json=json, headers=self._auth_headers())

                last_status = resp.status_code
                last_body = resp.text[:500] if resp.status_code != 200 else ""

                if resp.status_code == 200:
                    return cast("dict[str, Any]", resp.json())

                if resp.status_code == 429:
                    retry_after = self._parse_retry_after(resp)
                    wait = retry_after if retry_after else 0.5 * (attempt + 1)
                    logger.warning(
                        "Jupiter 429 rate limited (attempt %d/%d), waiting %.1fs",
                        attempt + 1, self._max_retries + 1, wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Non-retryable error
                break

            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise JupiterError(f"Request timed out: {exc}") from exc

        raise JupiterError(
            f"Jupiter API error (HTTP {last_status})",
            status_code=last_status,
            body=last_body,
        )

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        header = resp.headers.get("Retry-After")
        if not header:
            return None
        try:
            return max(0.0, float(header))
        except (TypeError, ValueError):
            return None

"""Tests for JupiterClient."""

from __future__ import annotations

import json
import re

import pytest
from pytest_httpx import HTTPXMock

from jupiter_swap import JupiterClient
from jupiter_swap.client import JupiterError

# -- Fixtures ----------------------------------------------------------------

QUOTE_RESPONSE = {
    "inputMint": "So11111111111111111111111111111111111111112",
    "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "inAmount": "1000000000",
    "outAmount": "150000000",
    "priceImpactPct": "0.01",
    "routePlan": [{"swapInfo": {"ammKey": "test"}}],
    "otherAmountThreshold": "149000000",
    "swapMode": "ExactIn",
    "slippageBps": 50,
}

SWAP_RESPONSE = {
    "swapTransaction": "base64encodedtx==",
    "lastValidBlockHeight": 123456789,
    "prioritizationFeeLamports": 500000,
}

ULTRA_ORDER_RESPONSE = {
    "requestId": "req-123",
    "inputMint": "So11111111111111111111111111111111111111112",
    "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "inAmount": "1000000000",
    "outAmount": "150000000",
    "transaction": "base64ultraTx==",
    "swapType": "swap",
    "prioritizationFeeLamports": 400000,
    "slippageBps": 42,
}

ULTRA_EXECUTE_RESPONSE = {
    "status": "Completed",
    "signature": "5xKg...",
}


# -- get_quote ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_quote_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        quote = await jup.get_quote(
            "So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            1_000_000_000,
        )

    assert quote.out_amount == "150000000"
    assert quote.price_impact_pct == "0.01"
    assert quote.swap_mode == "ExactIn"
    assert len(quote.route_plan) == 1


@pytest.mark.asyncio
async def test_get_quote_returns_raw(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        quote = await jup.get_quote("A", "B", 100)

    assert quote.raw == QUOTE_RESPONSE


@pytest.mark.asyncio
async def test_get_quote_amount_helpers(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        quote = await jup.get_quote("A", "B", 100)

    assert quote.in_amount_float == 1_000_000_000.0
    assert quote.out_amount_float == 150_000_000.0


@pytest.mark.asyncio
async def test_get_quote_http_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), status_code=500)

    async with JupiterClient(requests_per_second=0, max_retries=0) as jup:
        with pytest.raises(JupiterError, match="HTTP 500"):
            await jup.get_quote("A", "B", 100)


@pytest.mark.asyncio
async def test_get_quote_429_retry(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), status_code=429)
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(requests_per_second=0, max_retries=1) as jup:
        quote = await jup.get_quote("A", "B", 100)

    assert quote.out_amount == "150000000"


@pytest.mark.asyncio
async def test_get_quote_429_exhausted(httpx_mock: HTTPXMock) -> None:
    for _ in range(3):
        httpx_mock.add_response(url=re.compile(r".*/quote.*"), status_code=429)

    async with JupiterClient(requests_per_second=0, max_retries=2) as jup:
        with pytest.raises(JupiterError):
            await jup.get_quote("A", "B", 100)


# -- get_swap_transaction ----------------------------------------------------

@pytest.mark.asyncio
async def test_get_swap_transaction_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)
    httpx_mock.add_response(url=re.compile(r".*/swap$"), json=SWAP_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        quote = await jup.get_quote("A", "B", 100)
        swap = await jup.get_swap_transaction(quote, "WalletPubkey123")

    assert swap.swap_transaction == "base64encodedtx=="
    assert swap.last_valid_block_height == 123456789
    assert swap.priority_fee_lamports == 500000


@pytest.mark.asyncio
async def test_swap_includes_dynamic_slippage(httpx_mock: HTTPXMock) -> None:
    """Verify the swap request body includes dynamicSlippage: true."""
    httpx_mock.add_response(url=re.compile(r".*/swap$"), json=SWAP_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        from jupiter_swap.models import QuoteResponse
        quote = QuoteResponse(
            input_mint="A", output_mint="B",
            in_amount="100", out_amount="200",
            raw=QUOTE_RESPONSE,
        )
        await jup.get_swap_transaction(quote, "Wallet")

    request = httpx_mock.get_requests()[-1]
    body = json.loads(request.content)
    assert body["dynamicSlippage"] is True
    assert body["wrapAndUnwrapSol"] is True


# -- Base URLs ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_swap_url_keyless(httpx_mock: HTTPXMock) -> None:
    """Without an API key the keyless lite-api endpoint is used."""
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        await jup.get_quote("A", "B", 100)

    url = str(httpx_mock.get_requests()[0].url)
    assert url.startswith("https://lite-api.jup.ag/swap/v1/")


@pytest.mark.asyncio
async def test_default_swap_url_keyed(httpx_mock: HTTPXMock) -> None:
    """With an API key the keyed endpoint is used by default."""
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(api_key="test-key", requests_per_second=0) as jup:
        await jup.get_quote("A", "B", 100)

    url = str(httpx_mock.get_requests()[0].url)
    assert url.startswith("https://api.jup.ag/swap/v1/")


@pytest.mark.asyncio
async def test_v6_url_deprecated_alias(httpx_mock: HTTPXMock) -> None:
    """The legacy v6_url argument still overrides the default base URL."""
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(v6_url="https://old.example.test/v6", requests_per_second=0) as jup:
        await jup.get_quote("A", "B", 100)

    url = str(httpx_mock.get_requests()[0].url)
    assert url.startswith("https://old.example.test/v6/")


# -- Ultra API ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_ultra_order_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/order.*"), json=ULTRA_ORDER_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        order = await jup.ultra_order(
            "So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            1_000_000_000,
            taker="WalletPubkey",
        )

    assert order.request_id == "req-123"
    assert order.out_amount == "150000000"
    assert order.swap_transaction == "base64ultraTx=="
    assert order.swap_type == "swap"
    assert order.dynamic_slippage_bps == 42


@pytest.mark.asyncio
async def test_ultra_order_is_get_with_params(httpx_mock: HTTPXMock) -> None:
    """Ultra orders are fetched with GET + query params (POST body is 404)."""
    httpx_mock.add_response(url=re.compile(r".*/order.*"), json=ULTRA_ORDER_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        await jup.ultra_order("A", "B", 100, taker="WalletPubkey", slippage_bps=75)

    request = httpx_mock.get_requests()[-1]
    assert request.method == "GET"
    url = str(request.url)
    assert "taker=WalletPubkey" in url
    assert "slippageBps=75" in url


@pytest.mark.asyncio
async def test_ultra_order_error_surfaced(httpx_mock: HTTPXMock) -> None:
    """HTTP 200 with an `error` field must raise instead of returning an empty tx."""
    httpx_mock.add_response(
        url=re.compile(r".*/order.*"),
        json={
            "error": "Insufficient funds",
            "errorCode": 1,
            "errorMessage": "Insufficient funds",
            "requestId": "req-err",
            "transaction": "",
        },
    )

    async with JupiterClient(requests_per_second=0) as jup:
        with pytest.raises(JupiterError, match="Insufficient funds"):
            await jup.ultra_order("A", "B", 100, taker="WalletPubkey")


@pytest.mark.asyncio
async def test_ultra_execute_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/execute$"), json=ULTRA_EXECUTE_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        sig = await jup.ultra_execute("signedTx==", "req-123")

    assert sig == "5xKg..."


@pytest.mark.asyncio
async def test_ultra_execute_failed_status(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/execute$"),
        json={"status": "Failed", "error": "Slippage exceeded"},
    )

    async with JupiterClient(requests_per_second=0) as jup:
        with pytest.raises(JupiterError, match="execution failed"):
            await jup.ultra_execute("signedTx==", "req-123")


# -- Client lifecycle --------------------------------------------------------

@pytest.mark.asyncio
async def test_client_not_connected() -> None:
    jup = JupiterClient()
    with pytest.raises(JupiterError, match="not connected"):
        await jup.get_quote("A", "B", 100)


@pytest.mark.asyncio
async def test_client_context_manager(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        quote = await jup.get_quote("A", "B", 100)
        assert quote.out_amount == "150000000"


# -- Auth headers ------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_key_sent_as_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(api_key="test-key-123", requests_per_second=0) as jup:
        await jup.get_quote("A", "B", 100)

    request = httpx_mock.get_requests()[0]
    assert request.headers.get("x-api-key") == "test-key-123"


@pytest.mark.asyncio
async def test_no_api_key_no_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/quote.*"), json=QUOTE_RESPONSE)

    async with JupiterClient(requests_per_second=0) as jup:
        await jup.get_quote("A", "B", 100)

    request = httpx_mock.get_requests()[0]
    assert "x-api-key" not in request.headers

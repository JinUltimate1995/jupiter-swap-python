"""Tests for TokenClient."""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from jupiter_swap import TokenClient

TOKEN_INFO_RESPONSE = {
    "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "name": "USD Coin",
    "symbol": "USDC",
    "decimals": 6,
    "logoURI": "https://example.com/usdc.png",
    "tags": ["verified", "strict", "community"],
    "daily_volume": 1234567.89,
    "freeze_authority": None,
    "mint_authority": None,
}

BANNED_LIST_RESPONSE = [
    {"address": "ScamToken111111111111111111111111111111111"},
    {"address": "RugPull2222222222222222222222222222222222222"},
]

STRICT_LIST_RESPONSE = [
    {
        "address": "So11111111111111111111111111111111111111112",
        "name": "Wrapped SOL",
        "symbol": "SOL",
        "decimals": 9,
        "tags": ["strict"],
    },
    {
        "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "name": "USD Coin",
        "symbol": "USDC",
        "decimals": 6,
        "tags": ["strict", "verified"],
    },
]


@pytest.mark.asyncio
async def test_get_token_info(httpx_mock: HTTPXMock) -> None:
    # startup calls /banned first
    httpx_mock.add_response(url=re.compile(r".*/banned$"), json=[])
    httpx_mock.add_response(url=re.compile(r".*/tokens/v1/EPjF.*"), json=TOKEN_INFO_RESPONSE)

    async with TokenClient() as client:
        info = await client.get_token_info("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

    assert info.symbol == "USDC"
    assert info.decimals == 6
    assert info.is_verified is True
    assert info.is_banned is False


@pytest.mark.asyncio
async def test_get_token_info_unknown_token(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/banned$"), json=[])
    httpx_mock.add_response(url=re.compile(r".*/tokens/v1/Unknown.*"), status_code=404)

    async with TokenClient() as client:
        info = await client.get_token_info("UnknownMintAddress")

    assert info.is_verified is False
    assert info.name == ""


@pytest.mark.asyncio
async def test_is_banned_from_preloaded_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/banned$"), json=BANNED_LIST_RESPONSE)

    async with TokenClient() as client:
        assert await client.is_banned("ScamToken111111111111111111111111111111111") is True
        assert await client.is_banned("SafeToken333333333333333333333333333333333") is False


@pytest.mark.asyncio
async def test_is_verified(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/banned$"), json=[])
    httpx_mock.add_response(url=re.compile(r".*/tokens/v1/EPjF.*"), json=TOKEN_INFO_RESPONSE)

    async with TokenClient() as client:
        assert await client.is_verified("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v") is True


@pytest.mark.asyncio
async def test_get_strict_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/banned$"), json=[])
    httpx_mock.add_response(url=re.compile(r".*/strict$"), json=STRICT_LIST_RESPONSE)

    async with TokenClient() as client:
        tokens = await client.get_strict_list()

    assert len(tokens) == 2
    assert tokens[0].symbol == "SOL"
    assert tokens[1].symbol == "USDC"
    assert all(t.is_verified for t in tokens)


@pytest.mark.asyncio
async def test_token_info_cached(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/banned$"), json=[])
    httpx_mock.add_response(url=re.compile(r".*/tokens/v1/EPjF.*"), json=TOKEN_INFO_RESPONSE)

    async with TokenClient() as client:
        info1 = await client.get_token_info("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        info2 = await client.get_token_info("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

    # Should only have made 1 HTTP call for the token (plus 1 for banned list)
    assert info1.symbol == info2.symbol == "USDC"
    # 1 banned + 1 token info = 2 total requests (second is cached)
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_refresh_banned_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/banned$"), json=[])
    httpx_mock.add_response(url=re.compile(r".*/banned$"), json=BANNED_LIST_RESPONSE)

    async with TokenClient() as client:
        assert await client.is_banned("ScamToken111111111111111111111111111111111") is False
        count = await client.refresh_banned_list()
        assert count == 2
        assert await client.is_banned("ScamToken111111111111111111111111111111111") is True


@pytest.mark.asyncio
async def test_client_not_connected() -> None:
    client = TokenClient()
    with pytest.raises(RuntimeError, match="not connected"):
        await client.get_token_info("test")

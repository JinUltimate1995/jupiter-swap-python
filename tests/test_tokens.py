"""Tests for TokenClient (Jupiter Token API v2)."""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from jupiter_swap import TokenClient

TOKEN_ITEM = {
    "id": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "name": "USD Coin",
    "symbol": "USDC",
    "decimals": 6,
    "icon": "https://example.com/usdc.png",
    "tags": ["verified", "strict", "community"],
    "isVerified": True,
    "mintAuthority": None,
    "freezeAuthority": None,
    "stats24h": {"buyVolume": 600000.0, "sellVolume": 600000.0},
}

BANNED_UNAVAILABLE = {"status": 400, "message": "Invalid tag provided."}

VERIFIED_LIST_RESPONSE = [
    {
        "id": "So11111111111111111111111111111111111111112",
        "name": "Wrapped SOL",
        "symbol": "SOL",
        "decimals": 9,
        "tags": ["verified", "strict"],
        "isVerified": True,
    },
    TOKEN_ITEM,
]


@pytest.mark.asyncio
async def test_get_token_info(httpx_mock: HTTPXMock) -> None:
    # startup attempts the (removed) banned list first
    httpx_mock.add_response(url=re.compile(r".*/tag.*"), status_code=400, json=BANNED_UNAVAILABLE)
    httpx_mock.add_response(url=re.compile(r".*/search.*"), json=[TOKEN_ITEM])

    async with TokenClient() as client:
        info = await client.get_token_info("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

    assert info.symbol == "USDC"
    assert info.decimals == 6
    assert info.is_verified is True
    assert info.is_banned is False
    assert info.logo_uri == "https://example.com/usdc.png"
    assert info.daily_volume == 1200000.0


@pytest.mark.asyncio
async def test_get_token_info_unknown_token(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/tag.*"), status_code=400, json=BANNED_UNAVAILABLE)
    httpx_mock.add_response(url=re.compile(r".*/search.*"), json=[])

    async with TokenClient() as client:
        info = await client.get_token_info("UnknownMintAddress")

    assert info.is_verified is False
    assert info.name == ""


@pytest.mark.asyncio
async def test_get_token_info_no_exact_match(httpx_mock: HTTPXMock) -> None:
    """Search results without an exact id match yield an unknown TokenInfo."""
    httpx_mock.add_response(url=re.compile(r".*/tag.*"), status_code=400, json=BANNED_UNAVAILABLE)
    httpx_mock.add_response(url=re.compile(r".*/search.*"), json=[TOKEN_ITEM])

    async with TokenClient() as client:
        info = await client.get_token_info("SomeOtherMint111111111111111111111111111")

    assert info.is_verified is False
    assert info.address == "SomeOtherMint111111111111111111111111111"


@pytest.mark.asyncio
async def test_banned_list_unavailable_graceful(httpx_mock: HTTPXMock) -> None:
    """v2 removed the public banned list — calls degrade to False without errors."""
    httpx_mock.add_response(
        url=re.compile(r".*/tag.*"),
        status_code=400,
        json=BANNED_UNAVAILABLE,
        is_reusable=True,
    )

    async with TokenClient() as client:
        assert await client.is_banned("ScamToken111111111111111111111111111111111") is False
        assert await client.refresh_banned_list() == 0


@pytest.mark.asyncio
async def test_banned_list_loads_if_available(httpx_mock: HTTPXMock) -> None:
    """Forward-compat: a banned list is still loaded if an endpoint serves one."""
    httpx_mock.add_response(
        url=re.compile(r".*/tag.*"),
        json=[{"id": "ScamToken111111111111111111111111111111111"}],
    )

    async with TokenClient() as client:
        assert await client.is_banned("ScamToken111111111111111111111111111111111") is True


@pytest.mark.asyncio
async def test_is_verified(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/tag.*"), status_code=400, json=BANNED_UNAVAILABLE)
    httpx_mock.add_response(url=re.compile(r".*/search.*"), json=[TOKEN_ITEM])

    async with TokenClient() as client:
        assert await client.is_verified("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v") is True


@pytest.mark.asyncio
async def test_get_strict_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/tag.*"), status_code=400, json=BANNED_UNAVAILABLE)
    httpx_mock.add_response(url=re.compile(r".*/tag.*"), json=VERIFIED_LIST_RESPONSE)

    async with TokenClient() as client:
        tokens = await client.get_strict_list()

    assert len(tokens) == 2
    assert tokens[0].symbol == "SOL"
    assert tokens[1].symbol == "USDC"
    assert all(t.is_verified for t in tokens)


@pytest.mark.asyncio
async def test_token_info_cached(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=re.compile(r".*/tag.*"), status_code=400, json=BANNED_UNAVAILABLE)
    httpx_mock.add_response(url=re.compile(r".*/search.*"), json=[TOKEN_ITEM])

    async with TokenClient() as client:
        info1 = await client.get_token_info("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        info2 = await client.get_token_info("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

    assert info1.symbol == info2.symbol == "USDC"
    # 1 banned-list attempt + 1 token search = 2 requests (second token read is cached)
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_client_not_connected() -> None:
    client = TokenClient()
    with pytest.raises(RuntimeError, match="not connected"):
        await client.get_token_info("test")

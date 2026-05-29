"""
Jupiter Token API client — token verification, metadata, and banned detection.
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

import httpx

from .models import TokenInfo

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_URL = "https://tokens.jup.ag"

# Cache TTLs
_TOKEN_INFO_TTL: float = 300.0
_BANNED_LIST_TTL: float = 600.0


class TokenClient:
    """
    Async client for the Jupiter Token API.

    Provides token metadata, verification status, and banned token detection.

    Usage::

        async with TokenClient() as tokens:
            info = await tokens.get_token_info("EPjFWdd5...")
            print(info.symbol, info.is_verified)

            is_scam = await tokens.is_banned("ScamMint...")
    """

    __slots__ = (
        "_base_url",
        "_api_key",
        "_http",
        "_banned_mints",
        "_banned_loaded",
        "_cache",
        "_cache_ttl",
    )

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_TOKEN_URL,
        api_key: str = "",
        cache_ttl: float = _TOKEN_INFO_TTL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http: httpx.AsyncClient | None = None
        self._banned_mints: set[str] = set()
        self._banned_loaded: bool = False
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = cache_ttl

    # -- Lifecycle -----------------------------------------------------------

    async def __aenter__(self) -> TokenClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open HTTP client and preload the banned token list."""
        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers=headers,
        )
        await self._refresh_banned_list()

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http:
            await self._http.aclose()
            self._http = None

    # -- Public API ----------------------------------------------------------

    async def get_token_info(self, mint: str) -> TokenInfo:
        """
        Get token metadata and verification status.

        Args:
            mint: Token mint address.

        Returns:
            TokenInfo with name, symbol, decimals, verification flags.

        Raises:
            httpx.HTTPError: On network failure.
        """
        cached = self._get_cached(f"token:{mint}")
        if isinstance(cached, TokenInfo):
            return cached

        if self._http is None:
            raise RuntimeError("TokenClient not connected — call connect() first")

        resp = await self._http.get(f"{self._base_url}/tokens/v1/{mint}")

        if resp.status_code == 404:
            token = TokenInfo(
                address=mint,
                is_verified=False,
                is_banned=mint in self._banned_mints,
            )
            self._set_cached(f"token:{mint}", token)
            return token

        resp.raise_for_status()

        data = resp.json()
        tags = data.get("tags", [])
        token = TokenInfo(
            address=data.get("address", mint),
            name=data.get("name", ""),
            symbol=data.get("symbol", ""),
            decimals=data.get("decimals", 0),
            logo_uri=data.get("logoURI", ""),
            tags=tags,
            daily_volume=data.get("daily_volume"),
            freeze_authority=data.get("freeze_authority"),
            mint_authority=data.get("mint_authority"),
            is_verified="verified" in tags or "strict" in tags or "community" in tags,
            is_banned=mint in self._banned_mints,
        )
        self._set_cached(f"token:{mint}", token)
        return token

    async def is_banned(self, mint: str) -> bool:
        """Check if a token is on Jupiter's banned list (known scams)."""
        if mint in self._banned_mints:
            return True
        if not self._banned_loaded:
            await self._refresh_banned_list()
        return mint in self._banned_mints

    async def is_verified(self, mint: str) -> bool:
        """Check if a token is on the verified list."""
        info = await self.get_token_info(mint)
        return info.is_verified

    async def get_strict_list(self) -> list[TokenInfo]:
        """
        Get the strictly verified token list (vetted tokens only).

        Returns:
            List of TokenInfo for all strictly verified tokens.
        """
        cached = self._get_cached("strict_list")
        if isinstance(cached, list):
            return cast("list[TokenInfo]", cached)

        if self._http is None:
            raise RuntimeError("TokenClient not connected — call connect() first")

        resp = await self._http.get(f"{self._base_url}/tokens/v1/strict")
        resp.raise_for_status()

        tokens = []
        for item in resp.json():
            if isinstance(item, dict):
                tags = item.get("tags", [])
                tokens.append(TokenInfo(
                    address=item.get("address", ""),
                    name=item.get("name", ""),
                    symbol=item.get("symbol", ""),
                    decimals=item.get("decimals", 0),
                    logo_uri=item.get("logoURI", ""),
                    tags=tags,
                    daily_volume=item.get("daily_volume"),
                    freeze_authority=item.get("freeze_authority"),
                    mint_authority=item.get("mint_authority"),
                    is_verified=True,
                    is_banned=False,
                ))

        self._set_cached("strict_list", tokens, ttl=_BANNED_LIST_TTL)
        return tokens

    async def refresh_banned_list(self) -> int:
        """
        Manually refresh the banned token list.

        Returns:
            Number of banned tokens loaded.
        """
        await self._refresh_banned_list()
        return len(self._banned_mints)

    # -- Internal helpers ----------------------------------------------------

    async def _refresh_banned_list(self) -> None:
        if self._http is None:
            return
        try:
            resp = await self._http.get(f"{self._base_url}/tokens/v1/banned")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    self._banned_mints = {
                        item.get("address", item) if isinstance(item, dict) else str(item)
                        for item in data
                    }
                    self._banned_loaded = True
                    logger.debug("Loaded %d banned tokens", len(self._banned_mints))
        except Exception as exc:
            logger.warning("Failed to load banned token list: %s", exc)

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            expires, value = self._cache[key]
            if time.monotonic() < expires:
                return value
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any, ttl: float | None = None) -> None:
        self._cache[key] = (time.monotonic() + (ttl or self._cache_ttl), value)

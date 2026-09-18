"""
Jupiter Token API client — token metadata, verification, and quality signals.

Jupiter's Token API v2 (keyless tier on ``lite-api.jup.ag``):

- ``GET /tokens/v2/search?query=<mint or symbol>`` — token metadata
- ``GET /tokens/v2/tag?query=verified`` — the verified token list
- ``GET /tokens/v2/recent/{interval}`` — recently created tokens
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

import httpx

from .models import TokenInfo

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_URL = "https://lite-api.jup.ag/tokens/v2"

# Cache TTLs
_TOKEN_INFO_TTL: float = 300.0
_LIST_TTL: float = 600.0


def _daily_volume(item: dict[str, Any]) -> float | None:
    """Sum the 24h buy/sell volume stats when present."""
    stats = item.get("stats24h") or {}
    buy = stats.get("buyVolume")
    sell = stats.get("sellVolume")
    if buy is None and sell is None:
        return None
    try:
        return float(buy or 0.0) + float(sell or 0.0)
    except (TypeError, ValueError):
        return None


class TokenClient:
    """
    Async client for the Jupiter Token API.

    Provides token metadata, verification status, and best-effort banned
    detection.

    .. note::
        Jupiter removed the public banned-token list in Token API v2.
        ``is_banned()`` therefore returns ``False`` unless a custom set has
        been loaded; the method is kept for backwards compatibility.

    Usage::

        async with TokenClient() as tokens:
            info = await tokens.get_token_info("EPjFWdd5...")
            print(info.symbol, info.is_verified)
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
        """Open the HTTP client and attempt the (optional) banned list preload."""
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

        Uses ``/tokens/v2/search`` and returns the entry whose ``id`` matches
        ``mint`` exactly. Unknown mints return a ``TokenInfo`` with
        ``is_verified=False`` rather than raising.

        Args:
            mint: Token mint address.

        Returns:
            TokenInfo with name, symbol, decimals, verification flags.

        Raises:
            httpx.HTTPStatusError: On an unexpected HTTP error.
        """
        cached = self._get_cached(f"token:{mint}")
        if isinstance(cached, TokenInfo):
            return cached

        if self._http is None:
            raise RuntimeError("TokenClient not connected — call connect() first")

        resp = await self._http.get(f"{self._base_url}/search", params={"query": mint})

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
        item: dict[str, Any] | None = None
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and entry.get("id") == mint:
                    item = entry
                    break

        if item is None:
            token = TokenInfo(
                address=mint,
                is_verified=False,
                is_banned=mint in self._banned_mints,
            )
        else:
            token = self._parse_token(item)

        self._set_cached(f"token:{mint}", token)
        return token

    async def is_banned(self, mint: str) -> bool:
        """
        Check if a token is on the banned list.

        Jupiter Token API v2 no longer exposes a public banned list, so this
        returns ``False`` unless a custom list was loaded. Kept for backwards
        compatibility.
        """
        if mint in self._banned_mints:
            return True
        if not self._banned_loaded:
            await self._refresh_banned_list()
        return mint in self._banned_mints

    async def is_verified(self, mint: str) -> bool:
        """Check if a token is verified."""
        info = await self.get_token_info(mint)
        return info.is_verified

    async def get_strict_list(self) -> list[TokenInfo]:
        """
        Get the verified token list.

        Jupiter removed the dedicated ``/tokens/v1/strict`` endpoint in Token
        API v2; this now returns the ``verified`` tag list (a superset — its
        strictly vetted entries still carry a ``strict`` tag in
        ``TokenInfo.tags``).

        Returns:
            List of TokenInfo for all verified tokens.
        """
        cached = self._get_cached("verified_list")
        if isinstance(cached, list):
            return cast("list[TokenInfo]", cached)

        if self._http is None:
            raise RuntimeError("TokenClient not connected — call connect() first")

        resp = await self._http.get(f"{self._base_url}/tag", params={"query": "verified"})
        resp.raise_for_status()

        tokens: list[TokenInfo] = []
        data = resp.json()
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    tokens.append(self._parse_token(item))

        self._set_cached("verified_list", tokens, ttl=_LIST_TTL)
        return tokens

    async def refresh_banned_list(self) -> int:
        """
        Manually refresh the banned token list (best-effort).

        Jupiter Token API v2 has no public banned list; the refresh attempt
        degrades gracefully and returns the number of loaded mints (0 when
        the endpoint is unavailable).

        Returns:
            Number of banned tokens loaded.
        """
        await self._refresh_banned_list(force=True)
        return len(self._banned_mints)

    # -- Internal helpers ----------------------------------------------------

    def _parse_token(self, item: dict[str, Any]) -> TokenInfo:
        """Map a Token API v2 item to TokenInfo."""
        tags = item.get("tags") or []
        address = item.get("id", "")
        return TokenInfo(
            address=address,
            name=item.get("name", ""),
            symbol=item.get("symbol", ""),
            decimals=item.get("decimals", 0),
            logo_uri=item.get("icon", ""),
            tags=tags,
            daily_volume=_daily_volume(item),
            freeze_authority=item.get("freezeAuthority"),
            mint_authority=item.get("mintAuthority"),
            is_verified=bool(item.get("isVerified")) or "verified" in tags or "strict" in tags,
            is_banned=address in self._banned_mints,
        )

    async def _refresh_banned_list(self, *, force: bool = False) -> None:
        if self._http is None:
            return
        if self._banned_loaded and not force:
            return
        try:
            resp = await self._http.get(f"{self._base_url}/tag", params={"query": "banned"})
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    mints: set[str] = set()
                    for item in data:
                        if isinstance(item, dict):
                            mint = item.get("id") or item.get("address")
                        else:
                            mint = item
                        if mint:
                            mints.add(str(mint))
                    self._banned_mints = mints
                    logger.debug("Loaded %d banned tokens", len(self._banned_mints))
            else:
                logger.debug(
                    "Jupiter Token API v2 has no banned list (HTTP %s); is_banned() returns False",
                    resp.status_code,
                )
            self._banned_loaded = True
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

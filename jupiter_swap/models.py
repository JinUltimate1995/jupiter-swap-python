"""
Data models for Jupiter API responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class QuoteResponse:
    """Parsed quote from the Jupiter Swap API."""

    input_mint: str
    output_mint: str
    in_amount: str
    out_amount: str
    price_impact_pct: str = "0"
    route_plan: list[dict[str, Any]] = field(default_factory=list)
    other_amount_threshold: str = "0"
    swap_mode: str = "ExactIn"
    slippage_bps: int = 50
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def in_amount_float(self) -> float:
        """Input amount as float (divide by decimals yourself)."""
        try:
            return float(self.in_amount)
        except (TypeError, ValueError):
            return 0.0

    @property
    def out_amount_float(self) -> float:
        """Output amount as float (divide by decimals yourself)."""
        try:
            return float(self.out_amount)
        except (TypeError, ValueError):
            return 0.0


@dataclass(slots=True)
class SwapResponse:
    """Parsed swap transaction from the Jupiter Swap API."""

    swap_transaction: str
    last_valid_block_height: int = 0
    priority_fee_lamports: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class UltraOrder:
    """Response from Jupiter Ultra API — combined quote + swap in one call."""

    request_id: str
    input_mint: str
    output_mint: str
    in_amount: str
    out_amount: str
    swap_transaction: str
    swap_type: str = "swap"
    priority_fee_lamports: int = 0
    dynamic_slippage_bps: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class TokenInfo:
    """Token metadata from Jupiter Token API."""

    address: str
    name: str = ""
    symbol: str = ""
    decimals: int = 0
    logo_uri: str = ""
    tags: list[str] = field(default_factory=list)
    daily_volume: float | None = None
    freeze_authority: str | None = None
    mint_authority: str | None = None
    is_verified: bool = False
    is_banned: bool = False

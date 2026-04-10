"""Tests for data models."""

from __future__ import annotations

from jupiter_swap.models import QuoteResponse, SwapResponse, TokenInfo, UltraOrder


def test_quote_response_defaults() -> None:
    q = QuoteResponse(input_mint="A", output_mint="B", in_amount="100", out_amount="200")
    assert q.price_impact_pct == "0"
    assert q.swap_mode == "ExactIn"
    assert q.slippage_bps == 50
    assert q.raw == {}


def test_quote_amount_helpers() -> None:
    q = QuoteResponse(input_mint="A", output_mint="B", in_amount="1000000000", out_amount="150000000")
    assert q.in_amount_float == 1_000_000_000.0
    assert q.out_amount_float == 150_000_000.0


def test_quote_amount_helpers_invalid() -> None:
    q = QuoteResponse(input_mint="A", output_mint="B", in_amount="bad", out_amount="")
    assert q.in_amount_float == 0.0
    assert q.out_amount_float == 0.0


def test_swap_response_defaults() -> None:
    s = SwapResponse(swap_transaction="abc==")
    assert s.last_valid_block_height == 0
    assert s.priority_fee_lamports == 0


def test_ultra_order_fields() -> None:
    o = UltraOrder(
        request_id="r1",
        input_mint="A",
        output_mint="B",
        in_amount="100",
        out_amount="200",
        swap_transaction="tx==",
        swap_type="rfq",
        dynamic_slippage_bps=42,
    )
    assert o.swap_type == "rfq"
    assert o.dynamic_slippage_bps == 42


def test_token_info_defaults() -> None:
    t = TokenInfo(address="mint123")
    assert t.name == ""
    assert t.decimals == 0
    assert t.is_verified is False
    assert t.is_banned is False
    assert t.tags == []


def test_token_info_full() -> None:
    t = TokenInfo(
        address="mint123",
        name="Test Token",
        symbol="TEST",
        decimals=9,
        logo_uri="https://example.com/logo.png",
        tags=["verified", "strict"],
        daily_volume=1234.56,
        freeze_authority="auth1",
        mint_authority="auth2",
        is_verified=True,
        is_banned=False,
    )
    assert t.symbol == "TEST"
    assert t.decimals == 9
    assert t.daily_volume == 1234.56

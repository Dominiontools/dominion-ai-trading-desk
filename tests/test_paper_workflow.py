import pytest
from datetime import datetime, timezone
import json

from engine.paper_workflow import PaperSignal, PaperTradingDesk


def signal(**changes):
    values = dict(symbol="BTCUSDT", market="CRYPTO", side="BUY",
                  entry_price=100, stop_loss=99, take_profit=102,
                  quantity=0.1, spread_bps=2, estimated_slippage_bps=2,
                  quote_age_seconds=1, trailing_distance=0.5)
    values.update(changes)
    return PaperSignal(**values)


def test_full_paper_cycle_entry_trailing_stop_and_take_profit(tmp_path):
    desk = PaperTradingDesk(starting_equity=20, journal=tmp_path / "trades.jsonl")
    entry = desk.open_from_signal(signal())
    assert entry["event"] == "PAPER_ENTRY"
    assert entry["risk_amount"] == 0.1
    assert desk.snapshot()["orders_enabled"] is False
    held = desk.update_price("BTCUSDT", 101)
    assert held["event"] == "POSITION_HOLD"
    assert held["stop_loss"] == 100.5
    closed = desk.update_price("BTCUSDT", 102)
    assert closed["event"] == "PAPER_EXIT"
    assert closed["exit_reason"] == "TAKE_PROFIT"
    assert closed["realized_pnl"] == 0.2
    assert desk.snapshot()["open_position"] is None
    rows = [json.loads(line) for line in (tmp_path / "trades.jsonl").read_text().splitlines()]
    assert [row["event"] for row in rows] == ["PAPER_ENTRY", "POSITION_HOLD", "PAPER_EXIT"]


def test_risk_gate_rejects_risk_above_ten_cents():
    desk = PaperTradingDesk(starting_equity=20)
    result = desk.open_from_signal(signal(quantity=0.2))
    assert result["event"] == "ENTRY_BLOCKED"
    assert "PER_TRADE_RISK_EXCEEDED" in result["reasons"]


def test_one_open_position_limit():
    desk = PaperTradingDesk()
    assert desk.open_from_signal(signal())["event"] == "PAPER_ENTRY"
    result = desk.open_from_signal(signal(symbol="ETHUSDT"))
    assert result["reason"] == "MAX_OPEN_POSITIONS"


def test_stale_quote_and_daily_loss_fail_closed():
    desk = PaperTradingDesk()
    assert desk.open_from_signal(signal(quote_age_seconds=99))["event"] == "ENTRY_BLOCKED"
    desk._daily_realized_pnl = -0.4
    result = desk.open_from_signal(signal())
    assert "DAILY_LOSS_LIMIT_REACHED" in result["reasons"]


def test_stop_loss_closes_and_updates_equity():
    desk = PaperTradingDesk()
    desk.open_from_signal(signal())
    result = desk.update_price("BTCUSDT", 98)
    assert result["exit_reason"] == "STOP_LOSS"
    assert result["realized_pnl"] == -0.1
    assert desk.snapshot()["equity"] == 19.9


def test_sell_position_closes_at_target():
    desk = PaperTradingDesk()
    assert desk.open_from_signal(signal(side="SELL", entry_price=100,
                                        stop_loss=101, take_profit=98))["event"] == "PAPER_ENTRY"
    result = desk.update_price("BTCUSDT", 97)
    assert result["exit_reason"] == "TAKE_PROFIT"
    assert result["realized_pnl"] == 0.2


def test_open_position_and_realized_pnl_restore_after_engine_restart(tmp_path):
    journal = tmp_path / "persistent-paper.jsonl"
    first = PaperTradingDesk(starting_equity=20, journal=journal)
    first.open_from_signal(signal())
    restored_open = PaperTradingDesk(starting_equity=20, journal=journal)
    assert restored_open.snapshot()["open_position"]["symbol"] == "BTCUSDT"
    restored_open.update_price("BTCUSDT", 98)
    restored_closed = PaperTradingDesk(starting_equity=20, journal=journal)
    assert restored_closed.snapshot()["open_position"] is None
    assert restored_closed.snapshot()["equity"] == 19.9
    assert restored_closed.snapshot()["daily_loss_pct"] == 0.005


def test_manual_paper_close_rejects_nonpositive_price():
    desk = PaperTradingDesk()
    desk.open_from_signal(signal())
    with pytest.raises(ValueError):
        desk.close_position(0)

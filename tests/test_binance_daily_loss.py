from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from engine.binance_daily_loss import BinanceDailyLossLedger


def test_stop_loss_record_is_idempotent_and_counted_once(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "private" / "daily-loss.jsonl")
    now = datetime(2026, 11, 25, 10, tzinfo=timezone.utc)
    first = ledger.record_stop_loss(
        order_list_id="dominion123", symbol="BTCUSDT",
        planned_loss_quote="2.50", recorded_at=now,
    )
    second = ledger.record_stop_loss(
        order_list_id="dominion123", symbol="BTCUSDT",
        planned_loss_quote="2.50", recorded_at=now + timedelta(hours=1),
    )
    assert first == second
    assert ledger.loss_for_day(now=now) == Decimal("2.50")
    assert ledger.loss_for_day(now=now + timedelta(days=1)) == Decimal("0")


def test_daily_loss_ledger_rejects_conflicting_duplicate(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    now = datetime.now(timezone.utc)
    ledger.record_stop_loss(
        order_list_id="dominion123", symbol="BTCUSDT",
        planned_loss_quote="2.50", recorded_at=now,
    )
    with pytest.raises(RuntimeError, match="Conflicting duplicate"):
        ledger.record_stop_loss(
            order_list_id="dominion123", symbol="BTCUSDT",
            planned_loss_quote="3.00", recorded_at=now,
        )


def test_corrupt_daily_loss_ledger_fails_closed(tmp_path):
    path = tmp_path / "loss.jsonl"
    path.write_text("{bad-json", encoding="utf-8")
    ledger = BinanceDailyLossLedger(path)
    with pytest.raises(RuntimeError, match="ledger is invalid"):
        ledger.loss_for_day()


def test_daily_loss_is_summed_by_utc_date(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    ledger.record_stop_loss(
        order_list_id="loss001", symbol="BTCUSDT",
        planned_loss_quote="1.25",
        recorded_at=datetime(2026, 11, 25, 23, 30, tzinfo=timezone.utc),
    )
    ledger.record_stop_loss(
        order_list_id="loss002", symbol="ETHUSDT",
        planned_loss_quote="0.75",
        recorded_at=datetime(2026, 11, 26, 0, 30, tzinfo=timezone.utc),
    )
    assert ledger.loss_for_day(now=datetime(2026, 11, 25, 12, tzinfo=timezone.utc)) == Decimal("1.25")
    assert ledger.loss_for_day(now=datetime(2026, 11, 26, 12, tzinfo=timezone.utc)) == Decimal("0.75")

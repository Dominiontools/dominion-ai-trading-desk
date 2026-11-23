from engine.positions import SimulatedPosition, evaluate_exit, update_trailing_stop

def buy_position():
    return SimulatedPosition("p1", "XAUUSD", "GOLD", "BUY", 100, 95, 110, 1, trailing_distance=3)

def test_buy_stop_loss_exit():
    decision = evaluate_exit(buy_position(), 94)
    assert decision.should_close and decision.reason == "STOP_LOSS"

def test_buy_take_profit_exit():
    decision = evaluate_exit(buy_position(), 111)
    assert decision.should_close and decision.reason == "TAKE_PROFIT"

def test_trailing_stop_only_moves_in_favour():
    pos = buy_position()
    moved = update_trailing_stop(pos, 105)
    assert moved.stop_loss == 102
    unchanged = update_trailing_stop(moved, 103)
    assert unchanged.stop_loss == 102

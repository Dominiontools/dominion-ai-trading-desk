# Binance Testnet Risk Gate

The risk_execution module is a BUY-only Spot Testnet risk planner. It applies
the project policy: 0.5% maximum planned loss per trade, 2% daily loss stop,
and one open position maximum. It requires verified symbol filters, verified
account-tier taker fees, a fresh quote, acceptable spread/slippage, and
tick/step/minimum-notional compliance.

For $20 quote-currency equity, the planned per-trade risk ceiling is $0.10
and the daily loss ceiling is $0.40. Actual losses can exceed estimates due to
gaps, slippage, fees, partial fills, and execution failures.

## Important execution block

This module can prepare and validate an order plan, but its execute method
always blocks. The current Binance adapter places a plain GTC limit entry and
does not yet submit and verify protective stop-loss/take-profit orders after a
fill. Sending an entry without that protection would violate project risk
requirements. No testnet order is sent by these tests.

Still outstanding before any testnet order:
- Fetch and validate live Binance Testnet exchangeInfo filters and account balances.
- Obtain and verify the account's actual fee tier.
- Implement a tested protective-order lifecycle, including partial fills,
  OCO/bracket support where available, cancellation/reconciliation, and emergency handling.
- Add secure in-app credential entry and protected storage.
- Wire the risk gate into the phone service only after the above checks pass.
- Perform an explicitly authorized testnet order and verify its full lifecycle.

This is not connected to the phone dashboard and cannot trade. Production Binance
hosts are not supported by this adapter.

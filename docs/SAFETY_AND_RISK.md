# Safety and Risk Gate

The same conservative limits must be enforced by the strategy planner, portfolio risk gate, broker adapter, and position manager. A passing local check is never sufficient on its own to authorize an order.

Project default policy:
- Maximum planned risk per trade: **0.5% of equity**.
- Daily realized-loss stop: **2% of starting daily equity**.
- Maximum concurrent open positions: **1 across all connected markets**.
- Reject spreads above 20 basis points.
- Reject estimated slippage above 15 basis points (0.15%).
- Reject quotes older than 10 seconds.
- Reject incomplete, crossed, future-dated, or stale quotes.
- Reject disabled markets, unknown contract/lot rules, unverified fees, insufficient margin, and any proposal while the emergency stop is active.
- Every accepted entry must have a verified protective stop-loss and take-profit workflow; an entry without confirmed protection is not an acceptable open position.

For a $20 account, 0.5% is a maximum planned risk of $0.10 per trade and 2% is a $0.40 daily loss stop. These are ceilings, not guarantees: gaps, slippage, commissions, conversion, and execution failure can cause larger realized losses.

A passing decision is not a profitability assessment, broker-side validation, or permission to submit a live order. Broker-specific contract specifications, volume increments, minimum stop distances, leverage, margin, market hours, execution constraints, and order lifecycle reconciliation must be verified independently. Live-money trading remains locked until demo execution and safety tests have passed and the user explicitly approves it.

# Safety and Risk Gate

The first risk gate is deliberately conservative and is evaluated before any paper execution adapter can accept a trade intent.

Default policy:
- Maximum risk per trade: 1% of equity (hard configuration ceiling: 2%).
- Daily loss stop: 3%.
- Maximum concurrent open positions: 3.
- Reject spreads above 20 basis points.
- Reject estimated slippage above 15 basis points.
- Reject quotes older than 10 seconds.
- Reject disabled markets and any proposal while the emergency stop is active.

A passing decision means only that these basic configured checks passed. It is not a profitability assessment, a broker-side validation, or permission to submit a live order. Fees, contract specifications, leverage, correlated exposure, margin, market hours, and broker execution constraints still need dedicated checks before any demo execution adapter is built.

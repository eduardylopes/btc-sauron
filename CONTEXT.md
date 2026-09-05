# BTC Sauron

BTC Sauron summarizes Bitcoin market conditions and sends timely information to a Telegram audience. Its context is market observation, not trade execution or investment advice.

## Market signals

**Daily Report**:
A scheduled snapshot that combines market price, on-chain metrics, derivatives activity, ETF flows, search interest, and sentiment into one Telegram message.
_Avoid_: Digest, newsletter.

**Price Alert**:
A notification that a BTC price movement crossed a configured threshold for a time window and was not suppressed by its cooldown.
_Avoid_: Signal, trade alert.

**Cooldown**:
The period after a Price Alert during which the same time window cannot send another alert.
_Avoid_: Debounce, silence.

**Market Snapshot**:
The set of source observations collected for one Daily Report or Price Alert evaluation.
_Avoid_: Payload, response bundle.

**Indicator**:
A value derived from a time series to describe a Bitcoin market condition, such as MVRV, Puell Multiple, or a moving-average ratio.
_Avoid_: Metric, signal.

**Liquidation Window**:
The rolling 24-hour set of public OKX BTC perpetual liquidation events used to calculate long and short notional totals.
_Avoid_: Liquidation feed, liquidation cache.

## Delivery

**Telegram Audience**:
The configured Telegram chat that receives Daily Reports and Price Alerts.
_Avoid_: User, subscriber.

**Source Degradation**:
The absence of a non-critical public data source while the report continues with its remaining observations.
_Avoid_: Failure, outage.

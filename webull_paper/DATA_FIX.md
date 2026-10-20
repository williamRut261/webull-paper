# Webull sandbox data-path repair, October 16, 2026

## Evidence and root cause boundary

Inspected main `823ef61af1c7f6df0136b443cd8d760ceb810534`, scheduled run
38778099696 (October 15), and 38607631692 (October 14). Both staged before
close and reached 15:48 ET. October 15 reported 25 usable / 69 universe
snapshots and 44 `stale_or_invalid_time`, then failed inside an active
indicator. October 14 stopped on `Stale or future Webull quote for AGQ`.
Neither reached submission. October 14 read-only runs 38641017968 and
38642240978 selected GDXD using completed history after hours, not a valid
intraday replay; their after-hours snapshots were all stale.

A reproducible code defect compared snapshot trade times to `now` captured
BEFORE account/history/snapshot requests. Valid trades during those requests
were labeled future. October 15 took roughly seven seconds between initialization
and failure; October 14 roughly thirteen. The logs did not save trade times,
ages, history rows, or the failing symbol, so attributing all 44 rejections to
this defect or to entitlement would be unjustified. Actual stale/delayed data,
malformed timestamps, and history gaps remain possible. This patch makes the
next scheduled run distinguish those cases.

## Behavior

- Snapshot validation reads the clock after every batch has returned. Epoch
  milliseconds and timezone-aware ISO timestamps share the audit parser.
  Invalid, future, other-session, and older-than-1200-second quotes are rejected.
  Logs include normalized source timestamps, observation time, age, and age
  relative to signal start, without account IDs, credentials, or price payloads.
- The existing 20-minute **paper** allowance is unchanged. It is not a claim
  of real-time data. No timestamp tolerance, old-close substitution, forward-fill,
  alternate provider, or forced fallback branch is introduced.
- Missing history symbols may remain NaN for execution evaluation. An unused
  symbol's missing prior adjusted close no longer aborts an unrelated branch.
  Active metrics still use the unchanged evaluator, including all candidates
  of an active ranking and inverse-volatility weights. Failures name the
  required symbol, indicator, lookback, and missing dates. Selected assets
  also require validated raw execution prices.
- Completed history is aligned to exchange sessions, making missing sessions
  and an absent prior session explicit. Leading pre-inception gaps retain the
  original evaluator behavior. A pinned offline XNYS calendar enforces the
  existing regular-session-only policy: 15:48 <= ET < 15:55, holidays and early
  closes blocked. Early-close trading is not newly enabled. Calendar updates
  remain necessary for unforeseen exchange closures.
- Trade timestamps survive through sizing. Every active signal, target and held
  symbol is revalidated before the first order and before/after each preview.
  Expired inputs stop subsequent submissions; no diagnostic orders are sent.
- The 501-node Composer JSON and `strategy_engine.py` retain their upstream
  Git blob hashes. Conditions, thresholds, weights, symbols, indicator formulas,
  two-sample agreement, sandbox host, pinned account, daily claim, sell-before-buy,
  cash limits, and order cutoff are preserved.

## Data API and remaining limitations

The existing sandbox DataClient requests batch daily bars with
`timespan="D"`, `count="1200"`, `real_time_required=False`, excludes today's
incomplete daily bar, and requests stock snapshots in batches of ten.
Daily history is forward-adjusted; raw intraday prices are mapped onto the
prior adjusted close using `price * prior_adjusted_close / pre_close`.
That is the existing approximation, not independently verified Composer parity.

Webull documents [sandbox Data API hosts and millisecond snapshot examples](https://developer.webull.com/apis/docs/market-data-api/data-api/),
[forward-adjusted daily bars](https://developer.webull.com/apis/docs/reference/broker-market-data-api/bars-using-get/),
and [delayed sandbox data and entitlement limitations](https://developer.webull.com/apis/docs/market-data-api/faq/).
Mobile/desktop subscriptions are separate from OpenAPI. A valid timestamp
cannot establish entitlement or feed completeness. No subscription or account
settings are changed. Two samples from Webull are a stability check, not an
independent source. HTTP, permission and malformed-response failures still halt.
There is no promise that a run with genuinely stale REQUIRED inputs will trade.

## Verification

Offline tests cover receipt-time races, true future/stale timestamps, formats,
missing active and inactive inputs, active ranking candidates, internal history
gaps, absent prior sessions, missing history symbols, duplicate history records,
cutoffs/holidays/early closes, quote expiration during previews, and exact
Composer/evaluator fingerprints. Existing strategy and execution safety tests
are retained. No credentials or network are used by these tests.

A successful offline/CI run does not establish market-data entitlement, actual
next-session coverage, broker fills, or Composer runtime parity. Inspect the
next naturally scheduled run's `PAPER_SNAPSHOT_COVERAGE`,
`PAPER_REQUIRED_INPUT_BLOCKED`, `PAPER_ACTIVE_INPUTS`, two-sample agreement,
and order audit before declaring automated execution validated. Do not rerun
an old trading workflow or submit a test order to obtain that evidence.

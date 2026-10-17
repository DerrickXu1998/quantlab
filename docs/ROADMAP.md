# Engineering roadmap

Drafted September 2026. This is the working plan, not a commitment — re-read and
revise it whenever a phase finishes or a premise breaks. Each phase lists what
already exists, what is missing, and the concrete deliverables. Where a decision
was made it is recorded as such; open questions are marked **open**.

## Current state (the short version)

The warehouse works: ClickHouse holds append-only `price_bars`, Postgres holds
the catalog (`instruments`, `symbol_map`, `universe_snapshots`,
`universe_members`, `ingest_runs`), ingestion is human-triggered via
`make quantlab-data` in quantlab-data-pipeline, and everything runs on one Compute Engine VM deployed from
GitHub Actions (see `docs/DEPLOY.md`). Universes exist as a plugin abstraction
(`quantlab_data/universe/` (quantlab-data-pipeline): `static`, `lse`, `nasdaqtrader`) but there are no
index universes (S&P 500, FTSE 100) and no DB-backed user universes. There is
no real-time path yet — no IBKR integration (planned in Phase 4).

## Phase 0 — Infra hygiene: backups and monitoring

The single VM is fine. One disk failure taking the whole warehouse with it is
not. This phase is deliberately first: it is cheap and protects everything
after it.

- [ ] Nightly `pg_dump` of the catalog → GCS bucket (lifecycle rule: keep 30
      daily, 12 monthly).
- [ ] Nightly `clickhouse-backup` of the bars store → the same bucket.
- [ ] Restore drill, once, written down in `docs/PROD_OPERATIONS.md`. A backup
      that has never been restored is a hope, not a backup.
- [ ] GCP uptime check against `/api/v1/health` with alert to email.
- [ ] Disk-usage alert at 75% on the data volume.
- [ ] Compose resource limits (`cpus`, `mem_limit`) on the `ingest` service so
      a large ingest cannot starve the API.

**Decision: stay on one VM.** Multi-node ClickHouse, managed Postgres, and any
orchestration beyond Compose are premature until there is live-trading money or
a second user. The strategy is a boring, recoverable single node.

## Phase 1 — Universe registry and index universes

**Goal**: a universe is a first-class, named, point-in-time thing in Postgres.
Templates (S&P 500, FTSE 100, whole-exchange) and user-defined lists share one
mechanism, one snapshot model, one resolution path.

What exists:

- `UniverseSource` plugin contract (`quantlab_data/universe/base.py` (quantlab-data-pipeline)) with a
  registry; `static` (custom lists / CSV / watchlists) covers the ad-hoc case.
- `universe_snapshots` + `universe_members` (`001_catalog.sql`), append-only
  enforced by trigger — the point-in-time storage is already right.

What is missing:

- [ ] A `universes` registry table: `name`, `kind` (`index`, `exchange`,
      `user`), `params` (JSONB — e.g. the source plugin and its options),
      `owner`, `created_at`. Names are stable identifiers referenced by ingest,
      backtests, and strategy configs.
- [ ] Index membership sources: new `UniverseSource` implementations for
      S&P 500 and FTSE 100 (pragmatic sources: Wikipedia constituent tables,
      slickcharts; official SPDJ/FTSE lists are licensed). Current-membership
      only at this phase — see the survivorship note below.
- [ ] CLI: `universe-create`, `universe-list`, `universe-members NAME --asof`.
- [ ] Snapshot-on-ingest provenance: ingesting universe X resolves it, writes a
      new `universe_snapshots` row, and records `snapshot_id` in `ingest_runs`.
      Today's `universe-snapshot` only archives the *already-ingested*
      universe; that is a different (and still useful) thing.

**Survivorship bias — recorded decision.** Phase 1 ships current membership
only. Backtests over a current-constituent universe are optimistic (delisted
losers are missing). Historical point-in-time index membership is a paid-data
problem; revisit when strategies graduate from research to candidate-live, and
note the caveat on every backtest report until then.

## Phase 2 — Universe-driven ingestion (human admin process)

**Goal**: one command ingests a universe's history, chunked, resumable, with
coverage reporting. Deliberately human-triggered — no scheduler yet.

What exists: `ingest --universe X --param k=v` already resolves a registered
universe; `ingest_runs` makes re-runs resumable; `artifacts/run_ingest.sh`
chunks by hand.

- [ ] `make ingest-universe UNIVERSE=ftse100 START=2010-01-01` — thin wrapper;
      chunking (≤100 symbols per batch) moves *into* the ingest command,
      retiring `artifacts/batch_*.txt`.
- [ ] Coverage-by-universe report: "FTSE 100: 97/100 members with bars from
      2010, 3 rejected" — a universe lens over the existing `coverage` command.
- [ ] Append-only discipline kept: re-ingesting a range supersedes via
      `ReplacingMergeTree(run_id)`; nothing deletes.

**Open**: when "as we desire" becomes "nightly", add a systemd timer on the VM
calling the same command. Do not build scheduling before someone has wanted it
twice.

## Phase 3 — Universes in strategy tooling

**Goal**: strategies, experiments, and the API reference universes by name
instead of inline symbol lists. One definition, consumed by ingest, backtest,
and (later) live trading.

- [ ] REST endpoints:
      - `GET /api/v1/universes` — named universes (templates + user).
      - `GET /api/v1/universes/{name}/members?asof=YYYY-MM-DD` — point-in-time
        resolution. The `asof` parameter is the one that makes backtests
        honest.
- [ ] Strategy/experiment config accepts `universe: ftse100` wherever it now
      takes a symbol list.
- [ ] Frontend: universe picker wherever a symbol list is chosen today.

## Phase 3.5 — Strategy expressiveness gaps

**Goal**: close the gaps between the feature/signal catalog and what the
Strategy tab can express. Candidate strategies and the full gap analysis live
in `docs/STRATEGY_IDEAS.md` (2026-09-30); gap IDs continue the register in
`docs/AI_QUANT_BOOK_STRATEGY_PLAN.md` §3. Six strategies (A1–A6 there) are
buildable today with zero code — backtest those first.

- [ ] **F11** — port `squeeze` and `choppiness` as backend filter rules
      (follows the `adx-trend-filter` pattern; hours of work, unlocks the
      volatility-regime strategies B3).
- [ ] **U7** — frontend for custom signal rules. The backend already serves
      `indicator-threshold` / `indicator-crossover` / `fundamental-condition`
      templates via `/signal-templates` + `/custom-rules`; there is no UI to
      create them. Highest-leverage single UI item: makes the whole indicator
      catalog user-reachable without new backend rules.
- [ ] **F10 + U6** — portfolio-level execution: rank a universe by a feature,
      rebalance on a schedule, hold N positions at target weights. This is the
      one architecture decision here (per-instrument simulation becomes a
      portfolio pass); it unlocks cross-sectional momentum rotation (B1), the
      largest strategy family the research engine already has features for.
- [ ] **F12** — signal rules over `insider_activity` and
      `fca_short_interest` / `short_squeeze_score`. Scope: US insiders + UK
      shorts only; `finra_short_volume` has ~1 month of history and cannot
      backtest.
- [ ] **F13** — `sizing_from_score`: scale position size by the weighted
      combine score. Cheap once F10 exists; not worth doing standalone.

**Order** (decision): A1–A6 backtests → F11 → U7 → F10/U6 → F12/F13. F10 is
deliberately last of the big items: it should be designed with real backtest
evidence from A1–A6 in hand, not ahead of it.

## Phase 4 — Live market data (IBKR, US equities)

**Goal**: live US prices for two consumers, the Market tab (watching) and
deployed strategies (trading), without letting live data near anything a
backtest reads. Redesigned October 2026 for the S&P universe; it replaces the
September LSE tick-capture design.

Decisions:

- **Provider**: Interactive Brokers, full-exchange (consolidated) US L1,
  ~$10–15/mo and waived at ~$30/mo commissions. The free Cboe One/IEX feed is
  not used: a fraction of US volume is a different market from the one we
  trade.
- **Tiingo is the source of truth.** Live data is provisional and kept out of
  `price_bars`: it lives in its own ClickHouse database (`live.*`) and its own
  topics (`quantlab.live.*`), never on `quantlab.bars`, which carries
  warehouse replays. Nothing under `runs/` or `replay/` reads `live.*`.
- **No reconciliation, short retention.** A session's live rows are dropped
  once that date's Tiingo load succeeds (daily partitions, `DROP PARTITION`,
  `TTL 7 days` as the safety net). Live topics keep ~1 day. The only live data
  that survives is what a deployed strategy acted on, recorded on its
  `decisions` row in Postgres.
- **Venue mismatch accepted; rules are venue-neutral.** Intraday backtests run
  on the IEX minute feed (one venue); live bars are consolidated, so volume is
  ~30–50× larger and intraday ranges are wider. Rules use relative volume
  (today against the symbol's own history), not absolute thresholds, and live
  stop-hit rates are expected to exceed the backtest's.
- **Line budget**: ~100 concurrent IBKR market-data lines. Deployments are
  served first; Market tab subscriptions take what is left and expire when the
  tab closes. A symbol over budget says so ("not subscribed: line budget"),
  and never falls back to a simulation.

Shared foundation:

- [ ] `live-ingest` service (own `pyproject.toml` and image, same pattern as
      `backend/`): IB Gateway (headless, IBC for the daily restart and
      re-login) → `ib_async` collector. Own compose profile (`live`).
- [ ] Postgres `live_subscriptions` (symbol, consumer: `deployment` |
      `market`, owner, expires_at) is how the backend asks the collector for
      a symbol; `live_sessions` records each collector session for gap
      detection.
- [ ] Paper account first. Pacing, line limits and reconnect behaviour are
      where this design breaks, and finding that out should be free.

### 4a — Market tab: live intraday view for a few tickers

Replaces the simulated intraday mode (`useSimulatedSeries` in
`frontend/src/quantlab/market/useMarketData.ts`) with real prices, about one
tick per second.

- [ ] Subscribing a ticker in the Market tab adds a `market` row to
      `live_subscriptions`; the collector opens `reqMktData` (~250 ms
      snapshots) and publishes at most one tick per symbol per second to
      `quantlab.live.ticks` (last, bid, ask, cumulative volume, `ts_event`).
- [ ] Backfill, session open → now: on subscribe, one `reqHistoricalData`
      request for today's 1-minute TRADES bars (regular hours), served by
      `GET /api/v1/live/{symbol}/session`, so the chart opens with the day so
      far rather than an empty line. Seconds-level detail starts at
      subscription time.
- [ ] Continuous updates: `GET /api/v1/live/stream?symbols=…` (SSE, read with
      fetch as in `frontend/src/api/replay.ts`, since it needs the auth header)
      fed by **one** tailing consumer per API process that fans out in memory
      to every open tab. The existing `streaming/bus.py` consumer reads a
      finite replay from the start and cannot do this. Answers 503 when the
      broker or collector is absent, as the replay endpoint does.
- [ ] `DataMode` becomes `'historical' | 'live'`. Explicit states: Live, Stale
      (no heartbeat for ~10 s in regular hours), Market closed (shows the last
      Tiingo session), Feed offline (503), Not subscribed (line budget).
      Today's candle is marked "IBKR · provisional".
- [ ] `FeedProvider` (ticker tape, watchlist, positions, order ticket) moves
      to the same stream. The random walk survives only under the `demo`
      profile, labelled as simulated.

### 4b — Deployed strategies: 5-second bars aggregated to the strategy's bar

Live signals must come from bars built exactly like the backtest's, or live
and batch diverge for reasons that have nothing to do with the market.

- [ ] Each deployment's symbols get `deployment` rows in
      `live_subscriptions`; the collector opens `reqRealTimeBars` (5-second
      TRADES bars, regular hours only, built by IBKR from every trade, so the
      high and low are right) and writes them to `live.bars_5s`.
- [ ] One aggregator builds the strategy's frequency (`5m`, `15m`, `1h`,
      matching `BAR_FREQUENCIES`) from the 5-second bars on the backtest's
      boundaries: anchored at 09:30 ET, the same timestamp convention (bar
      start or end) as the pipeline's minute bars, and official auction
      prices for the open and close as `execution/minutes.py` uses. A bar is
      published to `quantlab.live.bars` only once it has closed.
- [ ] **Signals fire on bar close only.** The runner never evaluates a
      forming bar, because the backtest never sees one. Stops and targets are
      checked on every 5-second bar, which matches the backtest checking them
      against the minute range.
- [ ] Warm-up is Tiingo history from `price_bars_current` plus today's live
      bars; after the nightly Tiingo load, tomorrow's warm-up is Tiingo only.
- [ ] Postgres `deployments`, `decisions` (with the bar and last price the
      strategy saw), `orders`, `fills`.
- [ ] A test that feeds a recorded session of 5-second bars through the
      aggregator and asserts the 5m/15m/1h bars match a reference resample
      at every boundary, including the open and close.

Licensing (unchanged): broker-sourced data for a personal account largely
avoids exchange non-display licences. Internal use is fine; publishing derived
signals would need a derived-data licence.

## Fundamentals coverage (parallel track)

**Goal**: a fundamental rule's silence always means "the numbers said no",
never "there were no numbers". Independent of the phases above; each item can
land on its own. Measured against the live warehouse on 2026-09-30 with
`GET /api/v1/fundamentals/coverage` — re-measure before starting any item.

Done:

- [x] Runs record fact coverage (`coverage.facts`: concepts read, missing count
      per concept, the names that lacked one) and the results view warns when
      any name's gates could never open. A run where *no* selected name has any
      filing for the concepts its rules read is refused with 422 instead of
      recorded as an empty result — on the synthetic demo (which has no
      fundamentals) and on the warehouse alike. Migration
      `007_run_fact_coverage.sql`.

What is missing:

- [ ] **UK accounts (data gap D6).** 0 of 99 `.LON` names have any accounts
      concept; the only UK fundamental is FCA short interest (77 names).
      the pipeline's `ingest-ch-fundamentals` exists but has never populated this
      database. First establish whether Companies House returns *structured*
      accounts for listed plcs at all — many file in forms the ingest may not
      parse. **Open**: if not, the fallback is to exclude `.LON` names from
      fundamental strategies by design and say so in the StrategyLab coverage
      warning, rather than let the gate sit shut.
- [ ] **US accounts gaps (data gap D7).** Per rule, the share of the 534 `.US`
      names with every concept it reads: accrual-reversal 438,
      profitability-filter 437, pe-filter 425, pb-filter 399,
      revenue-growth 376, liquidity-filter 370, margin-filter /
      margin-expansion 334, leverage-filter 292. Before re-ingesting,
      split the gap into (a) structural — banks and REITs do not report
      revenue / gross profit / current assets under the tags we map — and (b)
      ingest-limited — names never fetched (`SEC_LIMIT` rather than
      `SEC_ALL=--all`) or tags not mapped in `tag_rank`. Only (b) is a fix;
      (a) becomes documentation.
- [ ] **Explain sparse fundamental signals in the UI.** All three are by
      design, and all three read as bugs:
      - filter-role rules never emit signals — they only gate another rule's
        entries (a filters-only strategy is rejected);
      - change rules fire about once per annual filing (AAPL revenue-growth:
        once in 6.7 years), so a short window can hold zero events;
      - defaults are real screens (pe-filter max 25, min ROE 10%, ±10% YoY,
        `max_stale_days` 455), so over an expensive universe a gate can
        legitimately never open.
      One line per case in StrategyLab next to the rule picker, and in the
      "No signals" empty state when the run read fundamentals.
- [ ] **Local-run guard.** Outside Compose the backend silently falls back to
      the synthetic demo unless both `QUANTLAB_DB_URL` and `QUANTLAB_CH_URL`
      are set (the root `.env` has both commented out). Fundamental runs are
      now refused there, but the fallback itself should log a warning at
      startup naming the missing variable.

## Phase 5 — Revisit infra scale-out (conditional)

Only when one of these is true: live trading with real money, a second human
user, or the Phase 0 disk alert firing on capacity rather than on a leak.

- ClickHouse replica or managed offering.
- Separate ingest VM if live ingest (Phase 4) must not share a failure domain with serving.
- Managed Postgres if the restore drill ever takes longer than the downtime we
  can tolerate.

## Explicit non-goals (for now)

- No Kubernetes, no multi-region, no service mesh. One VM, Compose, boring.
- No historical point-in-time index membership (see Phase 1 decision).
- No L2/order-book capture until a strategy demonstrably needs it — it changes
  the provider decision (IBKR depth is aggregated snapshots) and the licence
  cost by an order of magnitude.
- No redistribution of any market data. Everything is internal research use.

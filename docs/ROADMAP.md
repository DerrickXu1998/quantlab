# Engineering roadmap

Drafted September 2026. This is the working plan, not a commitment — re-read and
revise it whenever a phase finishes or a premise breaks. Each phase lists what
already exists, what is missing, and the concrete deliverables. Where a decision
was made it is recorded as such; open questions are marked **open**.

## Current state (the short version)

The warehouse works: ClickHouse holds append-only `price_bars`, Postgres holds
the catalog (`instruments`, `symbol_map`, `universe_snapshots`,
`universe_members`, `ingest_runs`), ingestion is human-triggered via
`make ingest`, and everything runs on one Compute Engine VM deployed from
GitHub Actions (see `docs/DEPLOY.md`). Universes exist as a plugin abstraction
(`src/quantlab/universe/`: `static`, `lse`, `nasdaqtrader`) but there are no
index universes (S&P 500, FTSE 100) and no DB-backed user universes. There is
no real-time path at all — no tick data, no IBKR integration.

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

- `UniverseSource` plugin contract (`src/quantlab/universe/base.py`) with a
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

## Phase 4 — Real-time tick ingest (IBKR)

**Goal**: live LSE L1 ticks captured to memory for strategies, batched into
ClickHouse for history. Full design discussion from September 2026; summary:

- **Provider**: Interactive Brokers. LSE UK L1 ≈ £1/mo (non-professional) /
  £56/mo (professional); L2 ≈ £7/mo. IBKR also gives on-demand historical
  backfill (`reqHistoricalData` bars, `reqHistoricalTicks` — tick history
  limited to ~3 years, strict pacing: ≤60 requests / 10 min). Deep multi-year
  tick history, if ever needed, is a separate one-time purchase (LSEG Tick
  History or a vendor) — **open**, not budgeted.
- **Architecture**: `tick-ingest` service (own `pyproject.toml`, own image,
  same monorepo — same pattern as `backend/`). IB Gateway (headless container)
  → feed handler (`ib_async`) → bounded in-memory queue → two taps: strategies
  read from memory; a batch writer flushes ~5k rows / 1s to ClickHouse.
  Optional Redpanda publish (`streaming` profile) for the UI.
- **New table**: `ticks` in ClickHouse (`instrument_id`, `ts_event`,
  `ts_ingest`, `tick_type`, `price`, `size`, `currency`, `source`,
  `session_id`), `MergeTree`, monthly partitions, `ORDER BY
  (instrument_id, ts_event, tick_type)`. Dual timestamps make latency
  histograms free.
- **Crash recovery**: gap detection via per-run `session_id` tracked in a
  Postgres `tick_ingest_runs` table + `reqHistoricalTicks` backfill. No WAL in
  v1.
- **Placement**: own compose profile (`ticks`), its own disk/volume sizing —
  tick volume is ~100–1000× bar volume and the Phase 0 disk alert is the tripwire.
- **Licensing**: non-display usage of exchange data in an algo triggers
  exchange non-display licences if sourced directly; broker-sourced data for a
  personal account largely avoids this. Storing ticks for internal backtesting
  is fine; publishing derived signals would need a derived-data licence.
- **Order**: paper account first. Pacing and reconnect behavior are where this
  design breaks, and finding that out should be free.

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
      `make ingest-ch-fundamentals` exists but has never populated this
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
- Separate ingest VM if tick capture must not share a failure domain with serving.
- Managed Postgres if the restore drill ever takes longer than the downtime we
  can tolerate.

## Explicit non-goals (for now)

- No Kubernetes, no multi-region, no service mesh. One VM, Compose, boring.
- No historical point-in-time index membership (see Phase 1 decision).
- No L2/order-book capture until a strategy demonstrably needs it — it changes
  the provider decision (IBKR depth is aggregated snapshots) and the licence
  cost by an order of magnitude.
- No redistribution of any market data. Everything is internal research use.

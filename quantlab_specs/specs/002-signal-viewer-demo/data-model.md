# Data Model: Dockerized Signal Viewer on Synthetic Data

**Feature**: `002-signal-viewer-demo` | **Date**: 2026-09-19
**Source**: entities from [spec.md](spec.md) Key Entities; storage decisions from
[research.md](research.md) (R3, R4, R5).

Storage is a single SQLite file in the `quantlab-data` Docker volume. DDL is applied by an
idempotent bootstrap (`CREATE TABLE IF NOT EXISTS …`) at seed time. All writes are
deterministic upserts keyed on natural keys, so reseeding produces a byte-identical
ordered dump (R8).

## Entity: Instrument

One fictitious tradable instrument in the demo universe (spec: Synthetic Instrument).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `symbol` | TEXT | PRIMARY KEY | Recognizably fake, e.g. `ZZTRND`, `ZZMEAN`, `ZZVOLT` (FR-006) |
| `name` | TEXT | NOT NULL | Fictitious company name |
| `currency` | TEXT | NOT NULL, fixed `USD` | Single-currency demo; no GBX/GBP concern |
| `regime_profile` | TEXT | NOT NULL | Which regime mix generated the history (`trending`, `mean_reverting`, `volatile`, `mixed`) — documents intent, not used by computation |
| `seed` | INTEGER | NOT NULL | Per-instrument derived seed (deterministic from `symbol`) |

Validation rules:
- `symbol` MUST match `[A-Z]{2,8}` and MUST NOT collide with any real ticker in a bundled
  denylist check at generation time (FR-006).

## Entity: PriceBar

One daily OHLCV bar for one synthetic instrument (spec: Price History). Raw data — persisted
before any signal computation and never mutated afterward (Constitution III).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `symbol` | TEXT | NOT NULL, FK → Instrument.symbol | |
| `date` | TEXT (ISO `YYYY-MM-DD`) | NOT NULL | Weekday-only fixed calendar, pinned as-of end date |
| `open` | REAL | NOT NULL, > 0 | |
| `high` | REAL | NOT NULL, `high >= max(open, close)` | |
| `low` | REAL | NOT NULL, `low <= min(open, close)`, > 0 | |
| `close` | REAL | NOT NULL, > 0 | |
| `volume` | INTEGER | NOT NULL, >= 0 | |

PRIMARY KEY (`symbol`, `date`).

Validation rules:
- Invariants above enforced by CHECK constraints; generation is the only writer.
- Coverage invariant: every instrument has exactly one bar per calendar day in the fixed
  range (≥ 3 years of weekdays, FR-004); gaps are a generation bug, not data.

## Entity: SignalRule

A registered signal-rule plugin (spec: Signal Rule). This table mirrors the plugin registry
at seed time so stored signals carry resolvable provenance; the registry in code is
authoritative, the table is its persisted snapshot.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `rule_name` | TEXT | NOT NULL | e.g. `sma-crossover`, `rsi-threshold`, `breakout-20d` |
| `rule_version` | TEXT | NOT NULL | Semver per plugin contract (Constitution II) |
| `parameters` | TEXT (JSON) | NOT NULL | Canonical JSON (sorted keys) — e.g. `{"fast":20,"slow":50}` |
| `lookback_days` | INTEGER | NOT NULL, > 0 | Minimum bars required before the rule may emit |
| `scale_class` | TEXT | NOT NULL, `scale_free` \| `price_scaled` | Per Constitution II |
| `direction_semantics` | TEXT | NOT NULL | Human-readable meaning of bullish/bearish for this rule |

PRIMARY KEY (`rule_name`, `rule_version`, `parameters`).

## Entity: Signal

One emitted signal event (spec: Signal).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Insert order is deterministic (ordered by symbol, date, rule) |
| `symbol` | TEXT | NOT NULL, FK → Instrument.symbol | |
| `date` | TEXT (ISO date) | NOT NULL | Signal date T |
| `rule_name` | TEXT | NOT NULL | Composite FK → SignalRule |
| `rule_version` | TEXT | NOT NULL | |
| `parameters` | TEXT (JSON) | NOT NULL | Copied from the rule snapshot for standalone provenance |
| `direction` | TEXT | NOT NULL, `bullish` \| `bearish` | |
| `trigger_values` | TEXT (JSON) | NOT NULL | Indicator values that fired the rule, canonical JSON, e.g. `{"sma_fast":101.2,"sma_slow":99.8}` |
| `data_window_end` | TEXT (ISO date) | NOT NULL, `<= date` | Latest bar date used as input — proves point-in-time correctness (VII) |

UNIQUE (`symbol`, `date`, `rule_name`, `rule_version`, `parameters`) — a rule fires at most
once per instrument per day.

Validation rules:
- `data_window_end <= date` enforced by CHECK constraint (look-ahead guard at the storage
  layer; the truncated-history sweep enforces it at the computation layer).
- Every signal MUST be re-derivable from PriceBar rows with `date <= data_window_end` plus
  the referenced SignalRule definition (SC-005).

## Relationships

```text
Instrument 1 ─── * PriceBar
Instrument 1 ─── * Signal
SignalRule  1 ─── * Signal
```

## Lifecycle / State

No mutable state transitions: all four tables are write-once per seed run. Reseeding
rebuilds from clean state (seed service drops and recreates the file), which is what makes
the interrupted-seed edge case safe — a half-written file is discarded, never resumed.

## Invariants Checked by Tests

1. Double-seed from clean state → identical ordered dump hash (FR-005, SC-002).
2. Every starter rule emits ≥ 1 signal across the dataset (FR-004, SC-003).
3. No signal with `data_window_end > date` can be inserted (VII).
4. Full re-derivation sweep: recomputing all rules from stored bars reproduces the stored
   signal set exactly (SC-005).

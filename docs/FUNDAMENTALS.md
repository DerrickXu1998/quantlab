# Fundamentals in strategies

5.7 million filed facts are sitting in the warehouse and nothing can reach them.
This is the design for connecting them to strategy generation, and the argument
for why the shape below is the only honest one.

Everything here was measured against the running warehouse on 2026-09-21, not
assumed. The numbers are reproducible with the queries in §1.

---

## 1. What is actually there

```
fundamentals:  5,713,359 rows
               580 instruments (of 644 in the catalog — 90%)
               18 mapped concepts, filed 2009-05-07 .. 2026-09-18
price_bars:    1,805,461 rows, 634 instruments, 2010-01-04 .. 2026-09-18
```

The table is already the right shape, and it is worth saying why, because the
design depends entirely on one column:

| column | why it matters |
|---|---|
| `period_end` | the fiscal period the number *describes* |
| `filed_at` | the date the number **became public** |
| `accession` | the filing it came from |
| `value`, `unit`, `concept`, `tag` | the fact itself, normalised and raw |
| `run_id` | which ingest produced it |

There is an index on `(instrument_id, concept, filed_at)` named
`fundamentals_pit_idx`, which is the access path every query below uses.

### The concepts

| family | concepts |
|---|---|
| Income statement | `revenue`, `gross_profit`, `operating_income`, `net_income` |
| Balance sheet | `total_assets`, `total_liabilities`, `equity`, `current_assets`, `current_liabilities`, `cash`, `long_term_debt`, `shares_outstanding` |
| Cash flow | `operating_cash_flow`, `capex` |
| Short interest | `net_short_position`, `short_volume`, `short_exempt_volume`, `total_volume` |

The first three families are quarterly and go back to 2009. **The short-interest
family is different in kind** and must not be treated the same way:
`net_short_position` is UK FCA disclosure (77 instruments, 2012→2026) and the
three volume concepts are FINRA daily short volume with **one month of history**
(502 instruments, 2026-08-20 → 2026-09-18). A backtest over 2015 that filters on
short volume would silently match nothing. §5 says what to do about that.

---

## 2. The point-in-time rule

This is the whole feature. Get it wrong and every backtest that touches
fundamentals is quietly, confidently wrong — and it will look *better*, not
worse, which is why nobody catches it.

**A filing repeats its prior periods.** Each 10-K restates the comparatives, so
one fact has many rows. Measured across the table: median 2 versions per
`(instrument, concept, period_end)`, p95 of 6, maximum 25.

Caterpillar's FY2023 revenue, verbatim from the warehouse:

| symbol | period_start | period_end | filed_at | value |
|---|---|---|---|---|
| CAT.US | 2023-01-01 | 2023-12-31 | **2024-02-16** | 67,060,000,000 |
| CAT.US | 2023-01-01 | 2023-12-31 | **2025-02-14** | 67,060,000,000 |
| CAT.US | 2023-01-01 | 2023-12-31 | **2026-02-13** | 67,060,000,000 |

One number, three filing dates. A naive join on `period_end` picks an arbitrary
one of these, and if it picks the 2026 row it has used a document from 2026 to
trade in 2024.

### The failure, demonstrated

This is not hypothetical. Both queries below were run against the warehouse,
asking the same question — *what were Caterpillar's figures on 2024-06-30?*

**The rule (`filed_at <= as_of`):**

| concept | value | period_end | filed_at | days stale |
|---|---|---|---|---|
| revenue | 15,799,000,000 | 2024-03-31 | 2024-05-01 | 60 |
| net_income | 2,854,000,000 | 2024-03-31 | 2024-05-01 | 60 |

Correct. On 30 June the newest *knowable* figures are Q1's, filed 1 May. Q2
ended that very day and was not filed until August, so a 60-day-stale Q1 number
is genuinely the best anyone had.

**The naive join (`period_end <= as_of`, ignoring `filed_at`):**

| concept | value | period_end | filed_at | filed **after** the as-of date by |
|---|---|---|---|---|
| net_income | 5,535,000,000 | 2024-06-30 | 2025-08-06 | **402 days** |
| revenue | 16,689,000,000 | 2024-06-30 | **2026-03-26** | **634 days** |

The second query trades 30 June 2024 on a document that did not exist until
March 2026. It looks entirely reasonable — the period ends on or before the
as-of date, which is the check most people would write — and it is wrong by
nearly two years. Nothing in the output announces this; the only column that
reveals it is `filed_at`, which the query never consults.

That is the whole argument for the rule, and for the inspector in §6 that shows
`filed_at` next to every value.

This is also why the *median lag from `period_end` to `filed_at` is 303–395
days* across the main concepts. That statistic is not "companies file late"; it
is "most rows are comparatives." A 40-day lag is the original filing. Anything
much larger is a restatement of an older period, and it is only knowable from
its own `filed_at`.

### The rule

> For an as-of date `D`, consider only rows with **`filed_at <= D`**. Within
> each `(instrument_id, concept)`, take the greatest `period_end`; break ties on
> the greatest `filed_at`. Forward-fill that value across trading dates until
> the next filing supersedes it.

### Scope: the refinement this rule needed

The rule as first written says "take the greatest `period_end`". Implementing it
against real data showed that is not quite enough, and the gap matters
financially.

Facts come in two shapes. A balance-sheet figure is an **instant** — equity *at*
2024-03-31. An income-statement figure is a **duration** — revenue *over* a
period, which may be a quarter or a full year, and the table holds both.

Taking the greatest `period_end` across both mixes them. Asked for Caterpillar's
revenue as known on 2024-06-30, it returns Q1's three-month figure of $15.8bn,
because Q1 ends later than FY2023 does. Put that in a P/E and the multiple is
wrong by roughly four times.

So duration concepts resolve at **annual** scope by default — FY2023's $67.06bn,
filed 2024-02-16 — while instant concepts take the latest quarter. Both are
equally point-in-time; the difference is which *period length* is the sensible
default, and for anything that will end up in a ratio it is the annual one.

The reader exposes scope explicitly so a rule that genuinely wants the quarter
can ask for it.

Three consequences, all load-bearing:

1. **Timing comes from `filed_at`, never `period_end`.** `period_end` answers
   "what period is this?", not "when could I have known it?".
2. **A restatement supersedes from its own filing date forward**, and never
   backwards. The backtest sees what the market saw.
3. **A fact is unusable before its first filing.** The first ~40 days of any
   period have no figure for that period, and the correct value is the
   *previous* period's, forward-filled — not a gap, and not the future one.

### The negative-lag rows

710 rows (0.012%) have `filed_at < period_end` — a filing carrying a
forward-dated period label. Spot-checked, these are genuine SEC tagging
oddities, not an ingest fault.

They are **harmless under the rule above**, because the rule keys on `filed_at`:
a row filed 2021-08-09 is knowable from 2021-08-09 whatever its period says. No
special handling. They are surfaced in the inspector (§4) as a data-quality note
rather than silently dropped, because dropping data because it looks strange is
how you end up with a clean dataset that is wrong.

---

## 3. What a user can build

Three capabilities, in increasing order of effort. They are deliberately ordered
so the first one alone is worth shipping.

### 3a. Fundamental filters — reuse the mechanism that exists

A strategy already has an `entry` / `exit` / `filter` role system, and a filter
already means "a state that gates an entry". A fundamental filter is exactly
that, with no new concept for the user to learn:

> Enter when RSI comes out of oversold, **while** P/E is under 20 and
> debt-to-equity is under 1.

| rule | gate is open when |
|---|---|
| `pe-filter` | trailing P/E is within `[min, max]` |
| `pb-filter` | price-to-book is within `[min, max]` |
| `profitability-filter` | return on equity ≥ `min_roe` |
| `leverage-filter` | total debt / equity ≤ `max_ratio` |
| `margin-filter` | operating margin ≥ `min_margin` |
| `liquidity-filter` | current ratio ≥ `min_ratio` |
| `short-interest-filter` | short volume share ≤ `max_share` *(see §5)* |

These compose with every technical rule already registered. That is the whole
point: no new screen, no new mental model, one new category in the catalogue.

### 3b. Fundamental change signals — entries and exits

Filters describe a state. These fire on a *change*, so they can open and close
positions:

| rule | fires when |
|---|---|
| `revenue-growth` | YoY revenue growth crosses `threshold` |
| `margin-expansion` | operating margin improves for `n` consecutive quarters |
| `earnings-surprise` | net income deviates from its own trend by `k` sigma |
| `accrual-reversal` | operating cash flow diverges from net income |

Each fires **on the filing date**, which is the only date the information
existed. A strategy built on these trades a handful of times a year per name —
the opposite cadence to the technical rules — and that is a feature, not a
limitation.

### 3c. Cross-sectional rank — later

"Top quintile by ROE within the selection." The library already has
`derived/cross_sectional.py`, and the ranking must be computed *as of each date*
with the same PIT rule. Deliberately last: it is the only one that needs the
whole universe in memory per date, and the first two deliver most of the value.

---

## 4. Backend design

### The reader

A new seam on the warehouse backend, alongside `load_bars_for`:

```python
def load_facts_for(
    symbols: list[str],
    concepts: list[str],
    start: str,          # the warm-up start, not the window start
    end: str,
) -> dict[str, FactSeries]
```

`FactSeries` is the PIT daily view: for each concept, the value **as known on
each trading date**, forward-filled from `filed_at`. Built once per run and
handed to the rules, so the SQL runs once rather than per rule per symbol.

The query is the rule in §2, expressed as a window function over
`fundamentals_pit_idx`:

```sql
SELECT DISTINCT ON (instrument_id, concept)
       instrument_id, concept, value, period_end, filed_at
FROM fundamentals
WHERE instrument_id = ANY($1) AND concept = ANY($2) AND filed_at <= $3
ORDER BY instrument_id, concept, period_end DESC, filed_at DESC
```

…evaluated per filing date rather than per trading date: pull every row with
`filed_at <= end`, then step the series forward in Python. One query per run.

### The rule contract

Signal rules take `bars` today. Fundamentals are a second input, so the contract
gains an optional keyword:

```python
def compute(bars, *, facts: FactSeries | None = None, **params) -> list[SignalEvent]
```

Backwards compatible: every existing rule ignores it. A rule that needs
fundamentals declares `requires_facts = ("revenue", "net_income")` at
registration, so the runner knows which concepts to load and the UI knows which
instruments will never trade.

### Why not compute ratios in SQL

P/E needs a price, and prices live in ClickHouse while facts live in Postgres.
Joining across two engines per date is worse than loading both series and
dividing in Python, where the PIT logic is already tested. Ratios are derived in
the rule, from two PIT-correct series.

---

## 5. Honesty requirements

These are not polish. Each one is a way the feature would otherwise lie.

1. **Coverage must be stated before the run.** 64 of 644 instruments have no
   fundamentals at all. A strategy with a fundamental filter over those names
   does not "find no trades" — it *cannot* trade, and the two are
   indistinguishable in a result. The builder must say
   *"7 of your 40 instruments have no fundamentals and will never trade."*

2. **Short-interest history must be stated.** FINRA volume concepts start
   2026-08-20. A filter using them over any earlier window matches nothing. The
   parameter form must show each concept's actual coverage window, read from the
   data, not hardcoded.

3. **The run must record its fundamental lineage.** Runs already record
   `ingest_run_ids` for bars. Facts need the same: a re-ingest that corrects a
   restatement changes results, and `ingest_run_ids` is the only thing that can
   explain why two identical configurations disagree.

4. **`assumptions` must gain a fundamentals line**, generated like the rest:
   *"Fundamentals are point-in-time on filing date; a restated figure applies
   from its own filing forward and never backwards."*

5. **A missing fact is not zero.** A name with no `equity` row has no
   book value, so P/B is undefined and the gate is **shut**, exactly as an
   un-warmed-up indicator is shut. It must never read as "cheap".

---

## 6. UI design

### Catalogue

A **Fundamentals** category beside trend / momentum / mean_reversion /
volatility / volume. The cards carry what the technical ones carry, plus the
concepts the rule needs and each concept's coverage.

### The inspector

A panel that answers *"what did this strategy actually know, and when?"* — the
question a fundamental backtest always raises and usually cannot answer.

For a selected instrument and date: concept, value, the period it describes, the
date it was filed, and how many days stale it was on that date. Restatements
shown as what they are — the same fact with a later filing date.

This is the screen that makes the PIT rule believable instead of a claim in a
docstring.

### In the builder

- Coverage warning as soon as a fundamental component is added (§5.1).
- Each parameter labelled in its own units — a P/E bound is a ratio, a margin is
  a percentage, and a form that treats them alike will be typed into wrongly.
- The plain-English sentence extends naturally: *"…while P/E is under 20."*

### In results

Fundamental coverage alongside the existing run coverage: how many instruments
had facts, and how many trades were gated out by a fundamental filter versus a
technical one. Without the second number, a strategy that filtered everything
away looks identical to one that found nothing.

---

## 7. What this is still not

- **Not a fundamental data vendor.** SEC EDGAR is US-only and public-domain;
  Companies House covers part of the UK and 10–20% of LSE issuers are
  Jersey/Guernsey-incorporated and simply absent. Constitution III.
- **Not survivorship-bias free.** The 580 names with fundamentals are names that
  exist *today*. Companies that went bankrupt — the ones a leverage filter would
  most want to have avoided — are not in the table.
- **Not restatement-complete.** The table has what EDGAR serves now. A figure
  restated before the first ingest has only its restated value.
- **Not a substitute for reading the filing.** A ratio built from two tagged
  numbers inherits every tagging decision the filer made.

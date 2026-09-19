# UI Contracts: Warehouse-Backed Experiments

The HTTP contract is [`openapi.yaml`](./openapi.yaml), which supersedes
`005-signal-research-workbench/contracts/openapi.yaml` as the authored source of truth. This file
covers the frontend-internal contracts, all of which are **additive** to feature 005's.

Rules carried forward and still binding:

1. Panel content components do not import the docking library (from `004`).
2. The front end performs no analytical computation (Constitution V) — it configures runs and renders
   what the backend returns. It does not decide which dataset is active, and must not infer it.

## 1. Dataset awareness

```ts
type Dataset = 'sqlite' | 'warehouse';
```

- The active dataset comes from the health response. The front end **reads** it; it never derives it
  from the shape of the data, the presence of fields, or configuration.
- It MUST be visible in the workbench without opening a menu or reading logs (FR-003). A researcher
  should never have to wonder whether a number came from synthetic data.
- When the warehouse is configured but unreachable, the interface MUST show that state rather than
  presenting an ordinary empty result (FR-004) — "no data" and "cannot reach the data" are different
  answers and must look different.

## 2. Run provenance

`Run` gains `dataset`, `instrument_ids`, `ingest_run_ids`, `corporate_actions` and `re_runnable`.

**Required presentation:**

- **Dataset is shown wherever a run's results are shown.** It sits alongside the model name and
  version in the provenance line, not in a detail panel — a warehouse result must never be mistakable
  for a demo result at a glance.
- **`re_runnable: false` renders the run read-only**, clearly marked as not reproducible under the
  current configuration (FR-012). Same treatment as `model_available: false` from feature 005: the
  run stays fully readable, only re-running is refused.
- **`corporate_actions` is surfaced with the results, not hidden.** A non-empty list means the price
  series contains unadjusted discontinuities, so any signal near an ex-date may be an artefact. This
  is a correctness warning, not a footnote — see the adjustment decision in `research.md` for why the
  system reports rather than adjusts.

## 3. Comparison

`RunCompare` gains one rule, and it is the important one:

- **When two runs have different `dataset` values, that difference is surfaced as prominently as a
  model-version difference** (FR-013), and the comparison should discourage reading the outcome
  difference as a parameter effect. Comparing a synthetic run against a real one is not a meaningful
  comparison, and the interface should say so rather than render a neat diff of two incomparable
  things.
- Differing `ingest_run_ids` with otherwise identical configuration means *the data changed
  underneath* — worth surfacing, because every input the researcher chose looks the same.

## 4. Instrument selection

- Instruments continue to come from `GET /instruments`; the front end does not know or care whether
  that list is twelve synthetic names or thousands of real ones.
- Because the warehouse universe can be far larger than the demo's, selection MUST remain usable at
  that scale (search/filter rather than a single long list), and the server's selection-size limit
  stays authoritative — client-side hints are a convenience, never the check.

## Explicitly not part of this contract

- **No dataset switching from the interface.** Which dataset is active is a deployment decision made
  at startup; exposing a switch would make every saved run's provenance ambiguous about when it was
  taken.
- **No price adjustment controls.** The system reports corporate actions and does not adjust; an
  as-of adjustment policy is a separate feature.
- **No ingest controls.** Ingesting data is out of scope for this feature.
- **No blending of datasets** in one run, one chart, or one comparison.

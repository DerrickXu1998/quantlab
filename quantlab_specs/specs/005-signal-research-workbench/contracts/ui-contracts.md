# UI Contracts: Signal Research Workbench

The HTTP contract is [`openapi.yaml`](./openapi.yaml) in this directory, which is the authored single
source of truth and supersedes `002-signal-viewer-demo/contracts/openapi.yaml`. This file covers the
**frontend-internal** contracts.

Two rules carry over from previous features and constrain everything below:

1. **Panel content components do not import the docking library** (from `004`). The workbench panels
   are ordinary components registered into the existing workspace.
2. **The front end performs no analytical computation** (Constitution V). It configures runs and
   renders what the backend returns. No filtering, scoring, or recomputation of signals client-side.

## 1. Panel registry additions

Three new entries join the existing `filters` / `signals` / `chart` panels in
`frontend/src/workspace/panels.tsx`:

```ts
export type PanelId =
  | 'filters' | 'signals' | 'chart'      // existing
  | 'catalog'                             // model catalog (FR-001)
  | 'runConfig'                           // parameters + dataset + run (FR-002/003/004/005)
  | 'runResults';                         // results, summary, coverage, compare (FR-007..009/013)
```

Panel ids are a compatibility surface: a saved layout stores only these ids, so adding these three is
safe, but renaming one later invalidates saved layouts (absorbed by `004`'s restore fallback).

## 2. Model catalog contract

```ts
interface ModelCatalogState {
  models: Model[];          // from GET /models — never a hardcoded list
  selected: Model | null;
  status: 'loading' | 'ready' | 'error';
}
```

- The catalog **MUST** be populated from `GET /models`. The existing hardcoded
  `RULES = ['sma-crossover', 'rsi-threshold', 'breakout-20d']` in `SignalFilters.tsx` is deleted as
  part of this work; leaving it would keep the constitutional gap open and make SC-002 unverifiable.
- Selecting a model publishes it to run configuration; it does not itself start anything.

## 3. Run configuration contract

```ts
interface RunConfig {
  modelName: string;
  modelVersion?: string;            // omit for the highest registered version
  parameters: Record<string, unknown>;  // overrides only; omitted keys take declared defaults
  symbols: string[];
  startDate: string;                // ISO date
  endDate: string;
}
```

**Required behavior:**

- The parameter form is **generated from the selected model's `ParamSpec[]`** — one control per
  declared parameter, typed by `type`, bounded by `minimum`/`maximum`/`choices`, seeded with
  `default`. No parameter names, types, or bounds may be hardcoded in the front end; a model with
  parameters nobody anticipated must still render a usable form (FR-002, SC-002).
- Client-side validation mirrors the declared constraints for immediate feedback, but is **never the
  only check** — the server validates independently and its rejection is authoritative (FR-003).
  Client validation is a convenience, not the contract.
- A validation failure is reported **against the specific parameter**, not as a form-level banner.
- Submitting sends only the overrides; the effective parameters come back on the run and are what
  get displayed, so what the researcher sees recorded is what actually executed.

## 4. Run lifecycle contract

```ts
interface RunsState {
  runs: Run[];                 // session history, newest first (FR-012)
  activeRunId: string | null;
  inFlight: boolean;
  cancel: () => void;          // aborts the in-flight request
}
```

- Starting a run sets `inFlight` and shows progress; the run is appended to `runs` on completion.
  A new run **never replaces** an earlier one (FR-012).
- `cancel()` aborts the in-flight request so the researcher is not left waiting. **Stated plainly:**
  this stops the client waiting, not the server computing — see `research.md`'s scaling boundary. The
  UI must not claim the computation was stopped.
- A failed run is added to history with its error and the configuration preserved, so the researcher
  can correct and retry without re-entering anything (FR-018).

## 5. Results presentation contract

```ts
interface RunResultsProps {
  run: RunDetail;
}
```

Required distinctions — these are the ones that make results trustworthy rather than merely present:

- **Zero signals is a success state**, rendered distinctly from a failure. A completed run with
  `signal_count === 0` shows an explicit "this model produced no signals over this selection"
  outcome, never an error treatment (FR-008, SC-004).
- **Coverage is shown with every signal count**, never separately or on demand: how many of the
  requested instruments had data, and how many had full warm-up history. A count without its
  denominator is not to be displayed (FR-009, SC-006).
- Signals are shown as a list and marked on the price chart, reusing the existing `CandlestickChart`
  (which already takes `bars` + `markerDate`) rather than introducing a second chart.

## 6. Comparison contract

```ts
interface RunCompareProps {
  left: Run;
  right: Run;
}
```

- Shows which configuration values differ (parameters, symbols, window) and how outcomes differ
  (signal counts, coverage).
- **When `left.model_version !== right.model_version`, that difference is surfaced prominently**, so
  a version change can never be read as a parameter effect (FR-014). This is a correctness
  requirement, not a nicety: it is the difference between a valid conclusion and an invalid one.

## 7. Saved experiments contract

- Save, list, reopen, and delete map to `PATCH /runs/{id}`, `GET /runs?saved_only=true`,
  `GET /runs/{id}`, and `DELETE /runs/{id}`.
- Deleting asks for confirmation first (FR-015).
- A run whose `model_available` is false renders read-only with its provenance and results intact,
  clearly marked as not re-runnable (FR-017).
- "Use as starting point" seeds a new `RunConfig` from a saved run **without mutating the saved
  original** (FR-016).

## Explicitly not part of this contract

- No model upload, no code execution, no file ingestion — out of scope by decision.
- No order placement, positions, or broker connectivity — "trading" is signal research here.
- No conversational assistant.
- No client-side recomputation or re-filtering of signals; the server is authoritative.

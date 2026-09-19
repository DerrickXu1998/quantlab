# Phase 1 Data Model: Signal Research Workbench

Two new persisted tables, one extended in-memory registry structure, and no change to the meaning of
any existing entity. Field constraints below are normative — implementation should not re-decide them.

## ParamSpec (new — in-memory, registry metadata)

What a model declares about one of its parameters. This is the source FR-002's configuration form is
built from and FR-003's validation runs against. Today's registry holds only a default value; this is
the structure that replaces it.

| Field | Type | Constraint |
|---|---|---|
| `name` | string | Required. Must match the keyword argument accepted by the rule's compute function. |
| `type` | enum | Required. One of `int`, `float`, `bool`, `enum`. |
| `default` | matches `type` | Required. Must itself satisfy `minimum`/`maximum`/`choices` — a default that violates its own constraints is a registration-time error, not a run-time surprise. |
| `minimum` | number \| null | Optional; `int`/`float` only. Inclusive. |
| `maximum` | number \| null | Optional; `int`/`float` only. Inclusive. Must be `>= minimum` when both are present. |
| `choices` | list \| null | Optional; required when `type` is `enum`. Must be non-empty. |
| `description` | string | Optional, human-readable, shown beside the field. |

**Backward compatibility**: a bare value in the existing `params={"fast": 20}` form is interpreted as
`{name: "fast", type: inferred from the value, default: 20}` with no bounds. Existing rules therefore
keep registering unchanged; bounds are added rule by rule.

**Validation rules** (enforced at registration, so a bad declaration fails loudly at import):

- `minimum`/`maximum` only on numeric types; `choices` only on `enum`.
- `default` must satisfy its own constraints.
- Every declared `name` must be an accepted keyword of the compute function.

## Model (new — in-memory, derived; the catalog entry)

The catalog view of a registered rule. Not stored; assembled from the registry at request time, which
is what makes FR-001/SC-002 true — registering a model makes it appear with no interface change.

| Field | Type | Notes |
|---|---|---|
| `name` | string | From registration. |
| `version` | string | From registration. `(name, version)` is the registry key. |
| `parameters` | list of ParamSpec | What the configuration form is built from. |
| `lookback_days` | integer ≥ 1 | Drives the warm-up window and the "date range too short" check. |
| `scale_class` | enum | `scale_free` \| `price_scaled`, per Principle II. |
| `direction_semantics` | string | Existing free text explaining what bullish/bearish mean for this rule. |

## ExperimentRun (new — persisted)

One execution and its provenance. This entity is what makes Principle VI's reproducibility claim
checkable: everything needed to reproduce the run is on the record.

| Field | Type | Constraint |
|---|---|---|
| `id` | string | Required, unique. Stable identifier used by the API and by saved experiments. |
| `model_name` | string | Required. |
| `model_version` | string | Required. Recorded explicitly so a later comparison can surface a version difference (FR-014) rather than mistaking it for a parameter effect. |
| `parameters` | JSON object | Required. The **effective** parameters — registered defaults merged with the user's overrides. Never the bare defaults when overrides were supplied. Serialized canonically so identical configurations compare equal. |
| `symbols` | JSON array of string | Required, non-empty. The requested instrument selection. |
| `start_date` | date | Required. `<= end_date`. |
| `end_date` | date | Required. |
| `status` | enum | Required. `completed` \| `failed`. A run that fails is recorded with its reason, not discarded. |
| `error` | string \| null | Required when `status = failed`; null otherwise. |
| `created_at` | timestamp | Required. Metadata about the run, never an input to computation (Principle VI forbids wall-clock inside computations). |
| `signal_count` | integer ≥ 0 | Required when completed. **Zero is a valid, meaningful result**, not an error. |
| `instruments_requested` | integer ≥ 1 | Required. Denominator for coverage. |
| `instruments_with_data` | integer ≥ 0 | Required. How many requested instruments actually had bars in the window. |
| `instruments_full_warmup` | integer ≥ 0 | Required. How many had the full `lookback_days` of history before `start_date`; the rest may under-report signals early in the window. |
| `name` | string \| null | Set when the researcher saves the run as a named experiment (FR-015); null for unsaved runs. |

**Why the three instrument counts.** A signal count without a denominator is uninterpretable
(FR-009/SC-006), and warm-up coverage is the difference between "this model found nothing" and "this
model could not have found anything yet" — the distinction that makes short-window results
trustworthy.

**State transitions**:

```text
[configured]  --(validation fails)-->  nothing persisted; error returned against the parameter
[configured]  --(run succeeds)------>  status=completed, counts + signals recorded
[configured]  --(run raises)-------->  status=failed, error recorded, configuration preserved
[completed]   --(researcher saves)-->  name set
[any]         --(researcher deletes)-> run and its signals removed together
```

## ExperimentSignal (new — persisted)

A signal produced by a run. **Deliberately a separate table from `signals`**: the existing table is
the Signal Viewer's source, and run output inserted there would appear in that viewer, silently
mixing exploratory output into the curated seeded set (see `research.md` and `plan.md`'s Complexity
Tracking).

| Field | Type | Constraint |
|---|---|---|
| `run_id` | string | Required, references `ExperimentRun.id`. Deleting a run deletes its signals. |
| `symbol` | string | Required, references a known instrument. |
| `date` | date | Required. Must fall within the run's `[start_date, end_date]` — warm-up-period signals are computed but not reported. |
| `direction` | enum | Required. `bullish` \| `bearish`, matching the existing constraint. |
| `trigger_values` | JSON object | Required. The indicator values that fired the rule. |
| `data_window_end` | date | Required. **Must be `<= date`** — the same point-in-time proof the existing `signals` table enforces by CHECK constraint, and the reason Principle VII survives this feature. |

Ordering is deterministic by `(symbol, date)`, mirroring the existing engine's guarantee so that two
identical runs are byte-comparable (Principle VI, SC-003).

## DatasetSelection (new — transient, not persisted on its own)

The data a run executes over: `symbols` plus `start_date`/`end_date`. Not a table — it is absorbed
into `ExperimentRun`, because a selection has no meaning or lifetime apart from the run that used it.

**Validation rules**:

- `symbols` non-empty, and every symbol must exist in the universe.
- `start_date <= end_date`.
- The window must be long enough for the model's `lookback_days`, otherwise the run is rejected
  before executing with an explanation — rather than returning a confusingly empty result.
- Selection size is bounded server-side (instruments × days); an over-large request is rejected up
  front with the limit stated, rather than blocking the API.

## Existing entities (unchanged)

- **Signal**, **PriceBar**, **Instrument**, **SignalRule mirror** — unchanged in shape, meaning, and
  storage. The seeded `signals` table keeps exactly its current contents and query path; nothing in
  this feature writes to it.

# Phase 0 Research: Signal Research Workbench

Every finding below was verified by reading the current backend source, not recalled. Two of them
change the shape of the feature materially, and one is a correctness trap that would have produced
quietly wrong research results.

## Finding: the registry stores parameter *values*, not parameter *definitions*

**What's actually there.** `quantlab.signals.registry.SignalRule` carries `params: dict[str, Any]`,
populated from the decorator, e.g. `params={"fast": 20, "slow": 50}` on `sma-crossover`. The
indicator registry has the identical shape. So today the system knows a rule's *default values* and
nothing else: no type, no permitted range, no description, no distinction between "this must be a
positive integer" and "this may be anything".

**Why it matters.** FR-002 requires publishing each parameter's "name, type, permitted range or
allowed values, and default", and FR-003 requires validating against those constraints. Neither is
satisfiable from a bare value dict. This is also the gap behind the front end hardcoding
`RULES = ['sma-crossover', 'rsi-threshold', 'breakout-20d']` — with no metadata to render a form
from, a hardcoded list was the only option.

**Decision**: extend the registry to accept explicit parameter specifications — per parameter: type,
default, permitted range or allowed values, and a description — while continuing to accept the
existing `params={"fast": 20}` shorthand by treating a bare value as `{default: value, type:
inferred}`. Existing rules keep working unchanged; richer metadata is added rule by rule.

**Rationale.** Constitution Principle II already requires plugins to declare their parameters and the
registry to expose parameter metadata for the front end to enumerate. The current value-only dict is
a thin implementation of an existing obligation, so enriching it is bringing the code into line
rather than inventing scope. Backward compatibility matters because the decorator is the registration
contract for every rule, and a breaking change would force all of them to be rewritten at once —
exactly what Principle II says adding a plugin must not require.

**Alternatives considered**: introspecting `inspect.signature` for type hints and defaults (rejected —
it recovers types and defaults but never ranges, so FR-003 validation would stay impossible, and it
makes the contract implicit and magical); requiring a JSON Schema per rule (rejected — heavier than
needed for a handful of scalar parameters, and pushes schema authoring onto every plugin author).

## Finding: the engine cannot run a rule with user-supplied parameters

**What's actually there.** `compute_signals` calls `rule.compute(bars, **rule.params)` — always the
parameters baked in at registration. It also records `parameters=dict(rule.params)` on each emitted
signal. There is no override path, which means the central verb of this feature ("run *this* model
with *these* settings") is not currently expressible.

**Decision**: allow per-run parameter overrides, and record the **effective** parameters (registered
defaults merged with overrides) on both the run and every signal it produces — never the registered
defaults.

**Rationale.** Recording registered defaults while having executed overrides would make provenance
a lie, breaking reproducibility (Principle VI) in the most damaging way: a run that cannot be
reproduced from its own record, with nothing to indicate it. The existing schema is already built for
this — `signals` is keyed on `(symbol, date, rule_name, rule_version, parameters)` and `signal_rules`
on `(rule_name, rule_version, parameters)`, so parameters are part of identity throughout.

## Finding (correctness trap): a naive date range silently produces misleading results

**The trap.** Rules declare `lookback_days` — `sma-crossover` declares 51, because SMA(50) must be
defined at both `T-1` and `T`. The engine already skips a symbol when `len(bars) < rule.lookback_days`.
If a run loads only the bars **inside** the requested window, then the first ~51 trading days of that
window can emit nothing, not because the model found nothing but because it had no history yet. A
researcher comparing a 3-month window against a 3-year window would be comparing warm-up artefacts
and would have no way to see that from the result.

**Decision**: load bars from `start − lookback` through `end`, execute over that extended series, and
then **report only signals dated within `[start, end]`**. The run records both the requested window
and whether full warm-up history was available for each instrument.

**Point-in-time check (Principle VII).** Reading bars *before* the window start is past data relative
to every emitted signal, so it cannot introduce look-ahead. The forbidden direction is a signal using
bars dated after itself, which the existing truncation sweep tests for. That sweep must be extended
to cover parameter-overridden runs, since overrides change lookback behaviour (e.g. a longer `slow`
window) and are new execution paths the sweep has never seen.

**Alternatives considered**: reporting warm-up-period signals with a flag (rejected — a signal inside
the requested window is either real or it isn't; flags invite being ignored); requiring the user to
pad the window themselves (rejected — pushes a subtle correctness requirement onto the researcher,
which is precisely the kind of error this tool should prevent).

## Decision: run output is stored separately from seeded signals

**The risk.** The `signals` table's uniqueness is `(symbol, date, rule_name, rule_version,
parameters)`. Experiment output would therefore insert *cleanly* into it — and then appear in the
Signal Viewer's `/signals` list, mixing exploratory runs into the curated seeded set with no
indication. The failure is silent and it corrupts the meaning of an existing screen.

**Decision**: a separate `experiment_signals` table keyed by run id (see `data-model.md`).

**Rationale.** Beyond keeping the viewer's meaning intact, it makes deleting a run trivially safe and
keeps the existing `/signals` query untouched — no new filter to remember. See Complexity Tracking in
`plan.md` for the rejected `run_id IS NULL` discriminator alternative and why a separate table makes
the wrong thing hard rather than merely discouraged.

## Decision: synchronous run execution, with an explicit scaling boundary

**What's actually there.** Every route in `api/routes.py` is a plain synchronous `def`; there is no
background job machinery, task queue, or async execution anywhere in the backend.

**The numbers.** The seeded universe is 12 instruments × roughly 3 years of weekday bars ≈ 9,400
bars total. Running one numpy-based rule over that is milliseconds.

**Decision**: execute runs synchronously within the request, bound the accepted selection size
server-side, and satisfy FR-006 by showing in-progress state in the UI and letting the user abort the
in-flight request.

**Stated honestly**: aborting a synchronous request stops the *client waiting*, not the server
computing. At this data scale that costs milliseconds of wasted work and is an acceptable trade. This
is a genuine scaling boundary, not a permanent design: if the universe grows to thousands of
instruments, or if models get materially more expensive, this must become a real background job with
a run-status endpoint. The endpoint shape in `contracts/openapi.yaml` (create a run, then fetch it by
id) is deliberately chosen so that change is additive rather than breaking.

**Alternatives considered**: building the background job now (rejected under the constitution's YAGNI
clause — machinery for a load that does not exist, on a demo dataset that completes in milliseconds);
streaming progress (rejected — same reason, plus it would need infrastructure the stack has none of).

## Decision: the contract document moves forward with this feature

The authored OpenAPI document currently lives at
`specs/002-signal-viewer-demo/contracts/openapi.yaml` and is the single source of truth (Principle V),
mirrored into `backend/contracts/` by `make sync-contract` and guarded by `make check-contract`.
This feature adds endpoints, so the authored document is superseded by
`specs/005-signal-research-workbench/contracts/openapi.yaml`, carrying all existing paths forward
unchanged plus the new ones. The generation and drift-check commands are re-pointed at the new
location, keeping exactly one authored home for the contract.

**Alternatives considered**: a second, additive contract document (rejected — two authored documents
for one API is precisely the duplication the Repository Structure principle forbids, and the
generated client can only come from one).

## Resolved: no new dependencies

Because the scope was settled as *registered models only* and *existing universe only*, this feature
needs no upload handling, no sandboxing, no model-scoring runtime (ONNX or otherwise), and no new
data adapters. The dependency-justification requirement in the Technology Stack policy is therefore
not engaged. This is worth stating plainly, because the broader-scope alternatives discussed before
speccing would each have pulled in significant new surface.

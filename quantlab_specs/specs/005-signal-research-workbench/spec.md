# Feature Specification: Signal Research Workbench

**Feature Branch**: `005-signal-research-workbench`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "please design the ui with this inspiration but focus quantitative signal discovery and trading where you would allow to load model and run on dataset for experiment" — supplied with the OpenBB Platform architecture diagram as visual reference.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a Model Against a Dataset and See What It Finds (Priority: P1)

A quant researcher wants to take one of the available signal models, point it at a set of instruments
over a date range, run it, and see exactly which signals it produced — on a chart, in a list, and as
a short summary — without writing code or leaving the workbench.

**Why this priority**: This is the core discovery loop and the whole point of the feature. Everything
else (tuning, comparing, saving) is elaboration on top of it. Today a researcher can only browse
signals that were generated offline; they cannot ask "what would *this* model with *these* settings
produce on *this* slice of data?" — which is the actual research question.

**Independent Test**: Can be fully tested by opening the workbench, choosing a model from the
catalog, accepting or adjusting its parameters, selecting instruments and a date range, running it,
and confirming the resulting signals appear with a summary of how many fired and where — delivering
a complete, useful research loop with no history or saving needed.

**Acceptance Scenarios**:

1. **Given** the workbench is open, **When** the researcher browses the model catalog, **Then** they
   see every model currently registered in the system, each with its name, version, and a
   description of what it does.
2. **Given** a model is selected, **When** its configuration is shown, **Then** the researcher sees
   that model's own parameters with their names, types, permitted ranges, and default values — not a
   generic or hardcoded form.
3. **Given** a configured model, **When** the researcher selects instruments and a start/end date and
   starts the run, **Then** the system reports progress and, on completion, presents the signals the
   model produced.
4. **Given** a completed run, **When** the researcher inspects the results, **Then** they can see the
   signals listed, marked on a price chart, and summarised (how many signals, across how many
   instruments, over what period).
5. **Given** a run that produced no signals at all, **When** it completes, **Then** the researcher
   sees a clear "no signals produced" outcome that is unmistakably distinct from a failure — a model
   finding nothing is a valid and informative research result.
6. **Given** a parameter value outside the model's permitted range, **When** the researcher tries to
   run, **Then** the problem is reported against that specific parameter before any run starts.

---

### User Story 2 - Tune, Re-run, and Compare (Priority: P2)

Having run a model once, the researcher wants to change a parameter, run it again, and see plainly
how the two runs differ — both in what was configured and in what came out — so they can tell whether
a change actually helped.

**Why this priority**: A single run answers "what does this do?"; comparison answers "which setting is
better?", which is what makes the tool a research instrument rather than a viewer. It depends on
User Story 1 existing but delivers separate value.

**Independent Test**: Can be fully tested by running one configuration, changing a single parameter,
running again, and confirming both runs remain available and can be compared side by side with their
differences in configuration and outcome made explicit.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the researcher changes a parameter and runs again, **Then**
   both runs are retained and individually inspectable — the earlier result is not overwritten.
2. **Given** two runs, **When** the researcher compares them, **Then** the comparison shows which
   configuration values differ and how the outcomes differ (signal counts, instruments covered).
3. **Given** two runs of the same model version with identical parameters and identical dataset
   selection, **When** their results are compared, **Then** the results are identical — a run is
   reproducible from its recorded configuration.
4. **Given** two runs produced by *different versions* of the same model, **When** they are compared,
   **Then** the version difference is shown prominently, so an apples-to-oranges comparison cannot be
   mistaken for a parameter effect.
5. **Given** a run, **When** the researcher views its details, **Then** they can see the full
   provenance needed to reproduce it: model name and version, every parameter value, the instruments,
   and the date window.

---

### User Story 3 - Keep and Reopen Named Experiments (Priority: P3)

A researcher who has found a configuration worth remembering wants to name it, keep it, and come back
to it later from a list — rather than reconstructing the setup from memory each session.

**Why this priority**: Valuable for continuity across sessions, but the workbench is already useful
without it: a researcher can run, tune and compare within a session. Safest of the three to defer.

**Independent Test**: Can be fully tested by naming and saving an experiment, reloading the
application, reopening it from the saved list, and confirming its configuration and results return
intact.

**Acceptance Scenarios**:

1. **Given** a run the researcher wants to keep, **When** they name and save it, **Then** it appears
   in a list of saved experiments.
2. **Given** saved experiments exist, **When** the researcher reopens one, **Then** its configuration
   and its results are restored without needing to re-run it.
3. **Given** a saved experiment, **When** the researcher wants a variation, **Then** they can use it
   as the starting point for a new run without altering the saved original.
4. **Given** a saved experiment whose model is no longer registered, **When** it is opened, **Then**
   its recorded configuration and results are still readable, and it is clearly marked as not
   currently re-runnable.
5. **Given** saved experiments, **When** the researcher no longer wants one, **Then** they can delete
   it, and deletion asks for confirmation first.

---

### Edge Cases

- **A model that produces nothing** must read as a result, not an error — see US1 scenario 5. This is
  the single most important distinction in the feature: silence from a model is information.
- **A long-running experiment** must show that it is still working, and must be cancellable; a
  researcher must never be left unable to tell a slow run from a hung one.
- **A run that fails partway** (bad parameter combination, unavailable data) must report what went
  wrong without discarding the researcher's configuration, so they can correct and retry.
- **Instruments with no data in the selected window** must be reported as coverage information
  (how many instruments actually had data) rather than silently shrinking the dataset — a signal
  count is meaningless without knowing what it was computed over.
- **A date range with too little history** for the model's lookback must be caught and explained
  before running, not produce a confusingly empty result.
- **A very large selection** (many instruments over a long window) must either complete within a
  reasonable time or tell the researcher up front that the selection is too large.
- **Two runs whose model version differs** must never be presented as a like-for-like comparison.
- **A saved experiment referencing instruments no longer in the universe** must still open and be
  readable.
- **Theme and layout**: the workbench's panels must follow the existing light/dark theme and be
  arrangeable like existing panels, rather than introducing a second, inconsistent layout system.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST present a catalog of all models currently registered in the system,
  discovered at runtime — adding or removing a registered model MUST change the catalog with no
  change to the interface itself.
- **FR-002**: For each model, the system MUST present its declared parameters, including each
  parameter's name, type, permitted range or allowed values, and default.
- **FR-003**: System MUST validate parameter values against the model's declared constraints and
  report violations against the specific parameter, before starting a run.
- **FR-004**: Users MUST be able to define a dataset for a run by selecting instruments from the
  existing universe and a start and end date.
- **FR-005**: Users MUST be able to start a run of the configured model over the selected dataset.
- **FR-006**: System MUST show that a run is in progress and allow the user to cancel it.
- **FR-007**: System MUST present the signals produced by a completed run as a list, marked on a
  price chart, and as a summary including signal count, instruments covered, and the period covered.
- **FR-008**: System MUST report a run that produced zero signals as a successful outcome that is
  visually and semantically distinct from a failed run.
- **FR-009**: System MUST report dataset coverage for a run — how many of the selected instruments
  actually had data in the selected window.
- **FR-010**: System MUST record, for every run, the provenance required to reproduce it: model name,
  model version, all parameter values, instrument selection, and date window.
- **FR-011**: Re-running a recorded configuration against the same data MUST produce identical
  results.
- **FR-012**: System MUST retain multiple runs within a session so that a new run does not overwrite
  an earlier one.
- **FR-013**: Users MUST be able to compare two runs, seeing both which configuration values differ
  and how the outcomes differ.
- **FR-014**: When two compared runs used different model versions, the system MUST make that
  difference prominent.
- **FR-015**: Users MUST be able to name and save an experiment, list saved experiments, reopen one
  with its configuration and results intact, and delete one after confirmation.
- **FR-016**: Users MUST be able to start a new run from a saved experiment's configuration without
  modifying the saved original.
- **FR-017**: A saved experiment whose model is no longer registered MUST remain readable and be
  marked as not currently re-runnable.
- **FR-018**: A run that fails MUST report the reason and preserve the user's configuration for
  correction and retry.
- **FR-019**: All workbench surfaces MUST follow the application's existing light/dark theme and
  behave as arrangeable panels consistent with the rest of the workspace.
- **FR-020**: All model execution MUST happen outside the user interface; the interface configures
  runs and displays results but performs no analytical computation itself.

### Key Entities

- **Model** *(registry-provided)*: An available signal model. Identified by name and version, and
  carrying a human-readable description and its declared parameter definitions (name, type,
  permitted values, default). The catalog is derived from what is registered, never from a fixed
  list held in the interface.
- **Parameter Definition**: One configurable input of a model — its name, type, permitted range or
  allowed values, and default. This is what the configuration form is built from.
- **Dataset Selection**: The data a run is executed over — a set of instruments from the existing
  universe plus a start and end date.
- **Experiment Run**: One execution. Holds its full provenance (model name and version, every
  parameter value, dataset selection), its status (running, completed, failed, cancelled), its
  results, and coverage information. Provenance is what makes a run reproducible and comparable.
- **Run Result**: What a run produced — the signals, plus summary statistics (signal count,
  instruments covered, period covered). A result with zero signals is a valid result.
- **Saved Experiment**: A named, retained Experiment Run the researcher chose to keep.
- **Signal**, **Price Bar**, **Instrument** *(existing)*: Unchanged in shape and meaning.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A researcher can go from opening the workbench to seeing the signals produced by a
  configured model in under 2 minutes, without consulting documentation.
- **SC-002**: When a new model is registered in the system, it appears in the catalog with its own
  parameters and is runnable, with no change made to the interface — verified by registering a model
  and observing it without redeploying the front end.
- **SC-003**: Re-running any recorded configuration reproduces its results identically, 100% of the
  time.
- **SC-004**: A run producing zero signals is correctly identified as a successful empty result, not
  a failure, in 100% of cases.
- **SC-005**: Given two runs, a researcher can state what differed in their configuration and what
  differed in their outcome without inspecting raw data by hand.
- **SC-006**: Every completed run reports what fraction of the selected instruments actually had data
  in the window, so no signal count is ever presented without its denominator.
- **SC-007**: A researcher returning in a later session can reopen a saved experiment and see the
  same configuration and results they left, with no re-running required.
- **SC-008**: No run leaves the researcher unable to distinguish "still working" from "stuck" — every
  in-progress run shows progress and can be cancelled.

## Assumptions

- **"Load a model" means selecting from the models already registered in the system**, configuring
  their declared parameters, and running them — confirmed with the requester. No model artifacts or
  code are uploaded through the interface. This deliberately keeps the feature free of any
  remote-code-execution surface, and builds on the plugin registry the project constitution already
  requires (declared name, version, parameter metadata, runtime discovery).
- **"Dataset" means the existing instrument universe plus a date range** — confirmed with the
  requester. Uploading data files and pulling from external sources are both out of scope here;
  either would be a separate feature with its own schema, validation, and (for external sources)
  licensing and rate-limit concerns.
- **This feature requires backend capability that does not exist yet.** Unlike the two preceding
  features, this is not a front-end-only change: there is currently no way to enumerate registered
  models with their parameter metadata, and no way to execute a model on demand over a chosen
  dataset. Notably, the current interface **hardcodes** its list of rules rather than discovering
  them, which is at odds with the constitution's requirement that the registry support runtime
  discovery; FR-001 and FR-002 bring that back into line.
- **"Trading" here means trading-signal research, not order execution.** Placing orders, tracking
  positions, and broker connectivity are out of scope: the system has no broker integration,
  no accounts, and no position model. If execution is wanted, it belongs in its own feature.
- **No AI assistant or chat is included.** The reference diagram features a copilot rail prominently,
  but the requester's framing maps that plug point onto *models*, not conversational agents. The
  structural ideas borrowed from the reference are the saved-work rail, the switchable analysis
  views, the grid of individually-parameterized panels, and the pluggable-model concept.
- **The workbench extends the existing workspace rather than replacing it.** The Signal Viewer
  continues to work; the workbench's surfaces are additional panels within the existing arrangeable
  layout, which is precisely the extensibility the docking workspace was adopted for.
- **Experiment runs and saved experiments are stored server-side with their provenance**, rather than
  in the browser. Results can be large and expensive to recompute, and the constitution already
  requires derived data to be stored with provenance (model name/version, parameters, data window).
- **Single-user application.** The reference's "shared with me" concept is out of scope, as the
  system has no accounts or authentication.
- **Reproducibility is a property of the system, not of this feature alone.** FR-011 and SC-003 rely
  on the existing guarantee that identical inputs, model versions, and parameters produce identical
  outputs.

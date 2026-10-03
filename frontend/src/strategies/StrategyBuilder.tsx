import { ChevronRight, FlaskConical, ServerCrash, TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Instrument } from '../api/client';
import type { CatalogModel, CombineLogic, RunV2, StrategyRole } from '../api/types';
import type { RunClone } from '../runs/RunsView';
import { COMBINE_LOGICS, ROLE_EXPLAINERS, ROLE_LABELS } from '../api/types';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { fieldClasses, Input, Select } from '../components/ui/field';
import { StatusBadge } from '../components/ui/status-badge';
import { navigate } from '../chrome/router';
import { Panel } from '../quantlab/chrome/Panel';
import { useRuns } from '../runs/RunsContext';
import { useDataWindow } from '../workbench/useDataWindow';
import { CoverageWarning } from './CoverageWarning';
import {
  BAR_FREQUENCIES,
  BAR_FREQUENCY_EXPLAINERS,
  BAR_FREQUENCY_LABELS,
  BARS_PER_SESSION,
  isIntraday,
  runSize,
  type BarFrequency,
} from './barFrequency';
import { ExecutionForm } from './ExecutionForm';
import { executionSummary } from './executionSummary';
import { isFundamental } from './fundamentals';
import { LibraryRail, type LibraryList } from './LibraryRail';
import { useFundamentalsCoverage } from './useFundamentals';
import { StrategyComponentEditor } from './StrategyComponentEditor';
import { SubmitBar } from './SubmitBar';
import { UniversePicker } from './UniversePicker';
import { templateToDraft, useStrategyTemplates } from './templates';
import {
  canFillRole,
  componentFor,
  describeStrategy,
  draftHasErrors,
  draftToSpec,
  draftBlockers,
  draftWarnings,
  emptyDraft,
  findModel,
  specToDraft,
  type Draft,
  type DraftComponent,
} from './strategyModel';
import { executedStrategyNames } from './StrategyStatus';
import { useStrategyLibrary } from './useStrategyLibrary';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

const LOGIC_LABELS: Record<CombineLogic, string> = {
  all: 'All must fire',
  any: 'Any may fire',
  majority: 'More than half',
  weighted: 'Weighted total',
};

const LOGIC_EXPLAINERS: Record<CombineLogic, string> = {
  all: 'Every component on this side has to be active. The most selective option, and the fewest trades.',
  any: 'One component is enough. The most permissive option, and the most trades.',
  majority: 'Strictly more than half of the components must be active.',
  weighted: 'Each component carries a weight; the active ones must add up to the threshold.',
};

const ROLE_ORDER: StrategyRole[] = ['entry', 'exit', 'filter'];

/** The four sections, in the order a strategy is thought through. */
export const SECTION_IDS = {
  strategy: 'configure-strategy',
  combine: 'configure-combine',
  universe: 'configure-universe',
  execution: 'configure-execution',
} as const;

/** A rule handed over from elsewhere (a signal row): added once as an entry. */
export interface StrategySeed {
  /** Identity of the handoff, so the same one is not applied twice. */
  key: string;
  model: string;
  values: Record<string, string>;
  symbols: string[];
}

/**
 * Configure: build a strategy and submit it as a backtest.
 *
 * Three things have to be true at once for someone who has never read the
 * contract: they can find a signal, they can see why a signal cannot be given
 * a role it does not support, and they can read back — in English — the thing
 * they have assembled before they spend a run on it. The summary sentence is
 * the last of those and is why it heads the first section.
 *
 * Submitting queues the run and leaves the builder as it is: backtests run in
 * the background and land in Runs, so the next variant can be set up and
 * submitted straight away rather than waiting on this one.
 */
export function StrategyBuilder({
  instruments,
  seed = null,
  clone = null,
  onShowRun,
}: {
  instruments: Instrument[];
  seed?: StrategySeed | null;
  /** A run's recorded configuration, from Runs → Clone to editor. Applied once. */
  clone?: RunClone | null;
  /** Open a submitted run in Runs. Defaults to navigating there. */
  onShowRun?: (runId: string) => void;
}) {
  const { catalog, modelsStatus, runError, submitStrategyRun, submitting, allRuns } = useRuns();
  const library = useStrategyLibrary();

  // Which strategies have actually been executed. Derived from the run
  // history rather than stored on the strategy, so deleting a run takes the
  // badge back down with it instead of leaving a claim nothing supports.
  const runNames = useMemo(() => executedStrategyNames(allRuns), [allRuns]);
  const templates = useStrategyTemplates();

  const [draft, setDraft] = useState<Draft>(() => emptyDraft());
  const [symbols, setSymbols] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [serverWarnings, setServerWarnings] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [queued, setQueued] = useState<RunV2 | null>(null);
  const [pendingReplace, setPendingReplace] = useState<{ label: string; apply: () => void } | null>(
    null,
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // The library opens on what is most useful: your strategies once you have
  // some, otherwise the signals to build the first one from.
  const [list, setList] = useState<LibraryList | null>(null);
  const shownList: LibraryList = list ?? (library.items.length > 0 ? 'mine' : 'signals');
  const { startDate, endDate, setStartDate, setEndDate } = useDataWindow(instruments);

  // Only asked for when the registry actually has a rule that reads filings:
  // a deployment with no fundamental rules has nothing to warn about, and the
  // request would buy an empty panel.
  const catalogHasFundamentals = useMemo(() => catalog.some(isFundamental), [catalog]);
  const fundamentals = useFundamentalsCoverage(catalogHasFundamentals);

  const sentence = useMemo(() => describeStrategy(draft, catalog), [draft, catalog]);
  const warnings = useMemo(
    () => [...new Set([...draftWarnings(draft), ...serverWarnings])],
    [draft, serverWarnings],
  );
  const hasErrors = useMemo(() => draftHasErrors(draft, catalog), [draft, catalog]);
  const blockers = useMemo(() => draftBlockers(draft), [draft]);
  const frequency: BarFrequency = draft.execution.bar_frequency ?? '1d';
  const unit = isIntraday(frequency) ? 'bars' : 'days';
  // The backend's own size check, run here first so an oversized run is
  // refused on screen rather than after a round trip.
  const size = useMemo(
    () => runSize(symbols.length, startDate, endDate, frequency, draft.components.length),
    [symbols.length, startDate, endDate, frequency, draft.components.length],
  );
  const summary = useMemo(() => executionSummary(draft.execution, unit), [draft.execution, unit]);
  const changedCount = summary.filter((item) => item.changed).length;

  // Unsaved changes: the spec as it would be sent, against the one last
  // loaded or saved. A brand-new draft counts as clean until it has content.
  const specKey = useMemo(() => JSON.stringify(draftToSpec(draft, catalog)), [draft, catalog]);
  const [baseline, setBaseline] = useState<string | null>(null);
  const dirty = baseline === null ? draft.components.length > 0 : specKey !== baseline;
  const markClean = useCallback(
    (next: Draft) => setBaseline(JSON.stringify(draftToSpec(next, catalog))),
    [catalog],
  );

  /** Replacing the draft asks first when it holds unsaved work. */
  const replaceDraft = (label: string, apply: () => void) => {
    if (dirty) {
      setPendingReplace({ label, apply });
    } else {
      apply();
    }
  };

  const setFrequency = (next: BarFrequency) =>
    setDraft((current) => ({
      ...current,
      execution: {
        ...current.execution,
        bar_frequency: next,
        // Minute accuracy and VWAP fills refine daily bars; an intraday run
        // already steps through the session, and the backend refuses both.
        ...(isIntraday(next)
          ? {
              intraday_resolution: 'daily' as const,
              fill_timing:
                current.execution.fill_timing === 'next_vwap'
                  ? ('next_typical' as const)
                  : current.execution.fill_timing,
            }
          : {}),
      },
    }));

  const addComponent = useCallback((model: CatalogModel, role: StrategyRole) => {
    setDraft((current) => ({ ...current, components: [...current.components, componentFor(model, role)] }));
    setNotice(`${model.name} added as ${ROLE_LABELS[role].toLowerCase()}.`);
  }, []);

  const updateComponent = (next: DraftComponent) =>
    setDraft((current) => ({
      ...current,
      components: current.components.map((component) =>
        component.id === next.id ? next : component,
      ),
    }));

  // A handoff lands once the registry can resolve its rule name.
  const appliedSeed = useRef<string | null>(null);
  useEffect(() => {
    if (!seed || appliedSeed.current === seed.key || modelsStatus !== 'ready') return;
    appliedSeed.current = seed.key;
    const model = findModel(catalog, seed.model);
    if (!model) {
      setNotice(`${seed.model} is not registered on this backend, so it could not be added.`);
      return;
    }
    const component = componentFor(model, canFillRole(model, 'entry') ? 'entry' : 'filter');
    component.values = { ...component.values, ...seed.values };
    setDraft((current) => ({ ...current, components: [...current.components, component] }));
    if (seed.symbols.length > 0) setSymbols(seed.symbols);
    setNotice(
      `${model.name} added as ${ROLE_LABELS[component.role].toLowerCase()} with the parameters it fired with. Add more signals, widen the universe, then submit.`,
    );
  }, [seed, catalog, modelsStatus]);

  // Clone to editor: the run's strategy, universe and window, as an unsaved
  // copy -- editing it must never overwrite whatever strategy it came from.
  const appliedClone = useRef<string | null>(null);
  useEffect(() => {
    if (!clone || appliedClone.current === clone.key || modelsStatus !== 'ready') return;
    appliedClone.current = clone.key;
    const { run } = clone;
    if (!run.strategy) return;
    const strategy = run.strategy;
    replaceDraft(`load the configuration of "${strategy.name}"`, () => {
      const loaded = { ...specToDraft(strategy, catalog), id: null };
      setDraft(loaded);
      setBaseline(null);
      setSymbols([...run.symbols]);
      setStartDate(run.start_date);
      setEndDate(run.end_date);
      setServerWarnings([]);
      setQueued(null);
      setNotice(
        `Loaded the configuration of "${strategy.name}" from a run of ${run.start_date} → ${run.end_date}. Change what you like and submit; save it to keep it.`,
      );
    });
    // replaceDraft reads `dirty` at the moment the clone arrives, which is
    // exactly when it should ask; re-running on every edit would not be.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clone, catalog, modelsStatus]);

  const removeComponent = (id: string) =>
    setDraft((current) => ({
      ...current,
      components: current.components.filter((component) => component.id !== id),
    }));

  const loadTemplate = (templateId: string) => {
    const template = templates.items.find((item) => item.id === templateId);
    if (!template) return;
    replaceDraft(`load "${template.name}"`, () => {
      const { draft: loaded, missing } = templateToDraft(template, catalog);
      setDraft(loaded);
      markClean(loaded);
      setSaveError(null);
      setServerWarnings([]);
      setNotice(
        missing.length === 0
          ? `Loaded "${template.name}". Change anything you like — nothing is saved until you press Save.`
          : `Loaded "${template.name}" without ${missing.join(', ')}: this backend does not register ${
              missing.length === 1 ? 'that rule' : 'those rules'
            }.`,
      );
    });
  };

  const loadStrategy = (strategy: (typeof library.items)[number]) =>
    replaceDraft(`open "${strategy.name}"`, () => {
      const loaded = specToDraft(strategy, catalog);
      setDraft(loaded);
      markClean(loaded);
      setServerWarnings(strategy.warnings ?? []);
      setNotice(`Loaded "${strategy.name}".`);
    });

  const startEmpty = () =>
    replaceDraft('start an empty strategy', () => {
      setDraft(emptyDraft());
      setBaseline(null);
      setServerWarnings([]);
      setNotice('Started an empty strategy.');
    });

  const save = async (asNew: boolean) => {
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await library.save(draftToSpec(draft, catalog), asNew ? null : draft.id);
      const next = { ...draft, id: saved.id, name: saved.name };
      setDraft(next);
      markClean(next);
      // The server reads the saved spec too, and its notes are the
      // authoritative ones -- surfaced verbatim rather than summarised away.
      setServerWarnings(saved.warnings ?? []);
      setNotice(`Saved as "${saved.name}".`);
    } catch (caught: unknown) {
      setSaveError(caught instanceof Error ? caught.message : 'the strategy could not be saved');
    } finally {
      setSaving(false);
    }
  };

  const canSubmit =
    !submitting && symbols.length > 0 && !hasErrors && blockers.length === 0 && !size.blocker;

  const submit = async () => {
    if (!canSubmit) return;
    // The inline spec, never the stored id: what runs is what is on screen,
    // including edits that have not been saved. A run pinned to an id would
    // quietly execute the last saved version instead.
    const run = await submitStrategyRun({
      strategy: draftToSpec(draft, catalog),
      symbols,
      start_date: startDate,
      end_date: endDate,
    });
    if (run) setQueued(run);
  };

  const showRun = (runId: string) =>
    onShowRun ? onShowRun(runId) : navigate('strategies', { tab: 'runs', run: runId });

  const jumpTo = (section: keyof typeof SECTION_IDS) => {
    if (section === 'execution') setAdvancedOpen(true);
    document.getElementById(SECTION_IDS[section])?.scrollIntoView({ block: 'start' });
  };

  const byRole = (role: StrategyRole) =>
    draft.components.filter((component) => component.role === role);

  const entryWeighted = draft.entry_logic === 'weighted';
  const exitWeighted = draft.exit_logic === 'weighted';

  if (modelsStatus === 'error') {
    return (
      <EmptyState
        testId="strategies-error"
        icon={ServerCrash}
        tone="error"
        title="Backend unreachable"
        detail="The signal registry could not be loaded, so there is nothing to build a strategy from. Start the stack and reload."
      />
    );
  }

  return (
    <div data-testid="strategy-builder" className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto lg:grid lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)] lg:overflow-hidden">
        <div className="flex min-h-0 flex-col border-b border-border p-4 lg:border-b-0 lg:border-r">
          <LibraryRail
            list={shownList}
            onListChange={setList}
            library={library}
            templates={templates}
            catalog={catalog}
            modelsLoading={modelsStatus === 'loading'}
            coverage={fundamentals.coverage}
            currentId={draft.id}
            runNames={runNames}
            onLoadStrategy={loadStrategy}
            onLoadTemplate={loadTemplate}
            onAdd={addComponent}
            onDeleted={(strategyId) =>
              setDraft((current) => (current.id === strategyId ? { ...current, id: null } : current))
            }
          />
        </div>

        <div className="min-h-0 space-y-4 p-4 lg:overflow-y-auto">
          {pendingReplace ? (
            <div
              role="alert"
              data-testid="replace-draft"
              className="flex flex-wrap items-center gap-2 border border-primary/40 bg-primary/5 p-3 text-sm"
            >
              <TriangleAlert size={16} strokeWidth={1.5} aria-hidden="true" className="shrink-0" />
              <p className="min-w-0 flex-1">
                {draft.name ? `"${draft.name}"` : 'This strategy'} has unsaved changes. Discard them to{' '}
                {pendingReplace.label}?
              </p>
              <Button type="button" size="sm" variant="outline" onClick={() => setPendingReplace(null)}>
                Keep editing
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  pendingReplace.apply();
                  setPendingReplace(null);
                }}
              >
                Discard and continue
              </Button>
            </div>
          ) : null}

          <div id={SECTION_IDS.strategy} className="scroll-mt-4">
            <Panel
              title="1 · Strategy"
              actions={
                <Button type="button" size="sm" variant="outline" onClick={startEmpty}>
                  New
                </Button>
              }
              bodyClassName="space-y-4"
            >
              {/* The single most important element on the screen: the assembled
                  strategy in a sentence, regenerated on every edit. It is how a
                  non-expert checks they built what they meant. */}
              <div className="border border-primary/40 bg-primary/5 p-3">
                <p className={MICRO}>In plain English</p>
                <p data-testid="strategy-summary" aria-live="polite" className="mt-1 text-sm leading-relaxed">
                  {sentence}
                </p>
              </div>

              {/* Directly under the sentence, and above the ordinary warnings:
                  this one says the strategy cannot do what the sentence just
                  claimed for part of the selection, and it is the last honest
                  moment before a number gets drawn from a run. */}
              <CoverageWarning
                draft={draft}
                catalog={catalog}
                symbols={symbols}
                startDate={startDate}
                endDate={endDate}
                coverage={fundamentals.coverage}
                status={fundamentals.status}
                message={fundamentals.message}
                onReload={fundamentals.reload}
                onInspect={(symbol) => navigate('research', { mode: 'company', symbol, as_of: endDate })}
              />

              {warnings.length > 0 ? (
                <ul data-testid="strategy-warnings" className="space-y-1">
                  {warnings.map((warning) => (
                    <li
                      key={warning}
                      role="alert"
                      className="flex gap-2 border border-border px-2 py-1.5 text-xs text-muted-foreground"
                    >
                      <TriangleAlert size={16} strokeWidth={1.5} aria-hidden="true" className="mt-px shrink-0" />
                      {warning}
                    </li>
                  ))}
                </ul>
              ) : null}

              {notice ? (
                <p role="status" data-testid="builder-notice" className="text-xs text-primary">
                  {notice}
                </p>
              ) : null}
              {saveError ? (
                <p
                  role="alert"
                  data-testid="builder-save-error"
                  className="border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-xs text-destructive"
                >
                  {saveError}
                </p>
              ) : null}

              {draft.components.length === 0 ? (
                <EmptyState
                  testId="builder-no-components"
                  icon={FlaskConical}
                  title="No components yet"
                  detail="Pick a signal from the Signals list and give it a role, or load one of the templates to see a finished strategy."
                  action={
                    shownList !== 'signals' ? (
                      <Button type="button" size="sm" variant="outline" onClick={() => setList('signals')}>
                        Show signals
                      </Button>
                    ) : undefined
                  }
                />
              ) : (
                ROLE_ORDER.map((role) => {
                  const components = byRole(role);
                  if (components.length === 0) return null;
                  return (
                    <section key={role} aria-label={`${ROLE_LABELS[role]} components`} className="space-y-2">
                      <h3 className={MICRO}>
                        {ROLE_LABELS[role]}
                        <span className="ml-2 normal-case tracking-normal">{ROLE_EXPLAINERS[role]}</span>
                      </h3>
                      <ul className="space-y-2">
                        {components.map((component) => (
                          <StrategyComponentEditor
                            key={component.id}
                            component={component}
                            model={findModel(catalog, component.rule_name)}
                            weighted={role === 'exit' ? exitWeighted : entryWeighted}
                            coverage={fundamentals.coverage}
                            onChange={updateComponent}
                            onRemove={() => removeComponent(component.id)}
                          />
                        ))}
                      </ul>
                    </section>
                  );
                })
              )}
            </Panel>
          </div>

          <div id={SECTION_IDS.combine} className="scroll-mt-4">
            <Panel
              title="2 · Combine"
              bodyClassName="grid grid-cols-1 gap-3 sm:grid-cols-2"
            >
              <div className="space-y-1">
                <label className={MICRO} htmlFor="entry-logic">
                  Entry logic
                </label>
                <Select
                  id="entry-logic"
                  value={draft.entry_logic}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, entry_logic: event.target.value as CombineLogic }))
                  }
                >
                  {COMBINE_LOGICS.map((logic) => (
                    <option key={logic} value={logic}>
                      {LOGIC_LABELS[logic]}
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">{LOGIC_EXPLAINERS[draft.entry_logic]}</p>
              </div>

              <div className="space-y-1">
                <label className={MICRO} htmlFor="exit-logic">
                  Exit logic
                </label>
                <Select
                  id="exit-logic"
                  value={draft.exit_logic}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, exit_logic: event.target.value as CombineLogic }))
                  }
                >
                  {COMBINE_LOGICS.map((logic) => (
                    <option key={logic} value={logic}>
                      {LOGIC_LABELS[logic]}
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">{LOGIC_EXPLAINERS[draft.exit_logic]}</p>
              </div>

              {/* Thresholds only mean something to weighted logic. */}
              {entryWeighted ? (
                <div className="space-y-1">
                  <label className={MICRO} htmlFor="entry-threshold">
                    Entry threshold
                  </label>
                  <Input
                    id="entry-threshold"
                    type="number"
                    step="any"
                    min={0}
                    value={String(draft.entry_threshold)}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, entry_threshold: Number(event.target.value) }))
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Net weight the firing entry components must reach before a position opens.
                  </p>
                </div>
              ) : null}

              {exitWeighted ? (
                <div className="space-y-1">
                  <label className={MICRO} htmlFor="exit-threshold">
                    Exit threshold
                  </label>
                  <Input
                    id="exit-threshold"
                    type="number"
                    step="any"
                    min={0}
                    value={String(draft.exit_threshold)}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, exit_threshold: Number(event.target.value) }))
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Net weight the firing exit components must reach before the position closes.
                  </p>
                </div>
              ) : null}

              <div className="space-y-1">
                <label className={MICRO} htmlFor="combine-window">
                  Agreement window
                </label>
                <Input
                  id="combine-window"
                  type="number"
                  min={1}
                  step="1"
                  value={String(draft.combine_window_days)}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, combine_window_days: Number(event.target.value) }))
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Components may agree within this many bars rather than only on the same bar. 1 means
                  "fired on this bar".
                </p>
              </div>
            </Panel>
          </div>

          <div id={SECTION_IDS.universe} className="scroll-mt-4">
            <Panel
              title="3 · Universe & window"
              actions={
                <StatusBadge tone="idle" title={BAR_FREQUENCY_EXPLAINERS[frequency]}>
                  {BAR_FREQUENCY_LABELS[frequency]}
                </StatusBadge>
              }
              bodyClassName="space-y-3"
            >
              <div className="space-y-1">
                <label className={MICRO} htmlFor="strategy-bars">
                  Bars
                </label>
                <Select
                  id="strategy-bars"
                  value={frequency}
                  aria-describedby="strategy-bars-explainer"
                  onChange={(event) => setFrequency(event.target.value as BarFrequency)}
                >
                  {BAR_FREQUENCIES.map((option) => (
                    <option key={option} value={option}>
                      {BAR_FREQUENCY_LABELS[option]}
                    </option>
                  ))}
                </Select>
                <p id="strategy-bars-explainer" className="text-xs text-muted-foreground">
                  {BAR_FREQUENCY_EXPLAINERS[frequency]}
                  {isIntraday(frequency)
                    ? ` Indicator periods, holding times and the agreement window count ${BAR_FREQUENCY_LABELS[frequency]} bars (${BARS_PER_SESSION[frequency]} a session). Percentage stops sized for daily bars will rarely trigger; ATR stops scale on their own. Positions may be held overnight.`
                    : ''}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className={MICRO} htmlFor="strategy-start">
                    Start
                  </label>
                  <input
                    id="strategy-start"
                    type="date"
                    className={fieldClasses}
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className={MICRO} htmlFor="strategy-end">
                    End
                  </label>
                  <input
                    id="strategy-end"
                    type="date"
                    className={fieldClasses}
                    value={endDate}
                    onChange={(event) => setEndDate(event.target.value)}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <p className={MICRO}>Universe</p>
                <UniversePicker instruments={instruments} selected={symbols} onChange={setSymbols} />
              </div>
            </Panel>
          </div>

          <div id={SECTION_IDS.execution} className="scroll-mt-4">
            <Panel
              title="4 · Execution"
              bodyClassName="space-y-3"
            >
              <details
                open={advancedOpen}
                onToggle={(event) => setAdvancedOpen((event.target as HTMLDetailsElement).open)}
                data-testid="execution-advanced"
              >
                <summary
                  className="flex cursor-pointer list-none items-start gap-2 text-xs"
                  aria-label={`Execution settings, ${changedCount} changed from the defaults`}
                >
                  <ChevronRight
                    size={16}
                    strokeWidth={1.5}
                    aria-hidden="true"
                    className={advancedOpen ? 'mt-px shrink-0 rotate-90' : 'mt-px shrink-0'}
                  />
                  <span className="min-w-0 flex-1" data-testid="execution-summary">
                    <span className={MICRO}>
                      Settings{changedCount > 0 ? ` · ${changedCount} changed` : ''}
                    </span>{' '}
                    {summary.map((item, index) => (
                      <span key={item.key}>
                        {index > 0 ? <span className="text-muted-foreground"> · </span> : null}
                        <span
                          title={item.caution}
                          className={item.changed ? 'text-foreground' : 'text-muted-foreground'}
                        >
                          {item.changed ? '● ' : ''}
                          {item.text}
                          {item.caution ? (
                            <TriangleAlert
                              size={16}
                              strokeWidth={1.5}
                              aria-label={item.caution}
                              className="ml-0.5 inline align-[-3px] text-destructive"
                            />
                          ) : null}
                        </span>
                      </span>
                    ))}
                  </span>
                </summary>
                <div className="mt-3">
                  <ExecutionForm
                    value={draft.execution}
                    onChange={(execution) => setDraft((current) => ({ ...current, execution }))}
                  />
                </div>
              </details>
            </Panel>
          </div>
        </div>
      </div>

      <SubmitBar
        name={draft.name}
        onNameChange={(name) => setDraft((current) => ({ ...current, name }))}
        saved={Boolean(draft.id)}
        dirty={dirty}
        saving={saving}
        onSave={() => void save(false)}
        onSaveAsCopy={() => void save(true)}
        size={size}
        components={draft.components.length}
        symbolsCount={symbols.length}
        blockers={blockers}
        hasErrors={hasErrors}
        warningCount={warnings.length}
        runError={runError}
        submitting={submitting}
        canSubmit={canSubmit}
        onSubmit={() => void submit()}
        queued={queued}
        onShowRun={showRun}
        onDismissQueued={() => setQueued(null)}
        onJump={jumpTo}
      />
    </div>
  );
}


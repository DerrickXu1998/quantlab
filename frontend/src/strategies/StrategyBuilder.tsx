import { BookMarked, FlaskConical, Hourglass, Play, ServerCrash, TriangleAlert } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import type { Instrument } from '../api/client';
import type { CatalogModel, CombineLogic, StrategyRole } from '../api/types';
import { COMBINE_LOGICS, ROLE_EXPLAINERS, ROLE_LABELS } from '../api/types';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { fieldClasses, Input, Select } from '../components/ui/field';
import { StatusBadge } from '../components/ui/status-badge';
import { RunResultsView } from '../components/RunResultsView';
import { Panel } from '../quantlab/chrome/Panel';
import { useRuns } from '../runs/RunsContext';
import { useDataWindow } from '../workbench/useDataWindow';
import { ExecutionForm } from './ExecutionForm';
import { SignalCatalogue } from './SignalCatalogue';
import { StrategyComponentEditor } from './StrategyComponentEditor';
import { templateToDraft, useStrategyTemplates } from './templates';
import {
  componentFor,
  describeStrategy,
  draftHasErrors,
  draftToSpec,
  draftWarnings,
  emptyDraft,
  findModel,
  specToDraft,
  type Draft,
  type DraftComponent,
} from './strategyModel';
import { useStrategyLibrary } from './useStrategyLibrary';

const MICRO = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

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

/**
 * The strategy builder.
 *
 * Three things have to be true at once for someone who has never read the
 * contract: they can find a signal, they can see why a signal cannot be given
 * a role it does not support, and they can read back — in English — the thing
 * they have assembled before they spend a run on it. The summary sentence is
 * the last of those and is the reason the rest of this screen is arranged
 * around it.
 */
export function StrategyBuilder({ instruments }: { instruments: Instrument[] }) {
  const { catalog, modelsStatus, activeRun, inFlight, runError, startStrategyRun, cancel } =
    useRuns();
  const library = useStrategyLibrary();
  const templates = useStrategyTemplates();

  const [draft, setDraft] = useState<Draft>(() => emptyDraft());
  const [symbols, setSymbols] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [serverWarnings, setServerWarnings] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [armedDelete, setArmedDelete] = useState<string | null>(null);
  const { startDate, endDate, setStartDate, setEndDate } = useDataWindow(instruments);

  const sentence = useMemo(() => describeStrategy(draft, catalog), [draft, catalog]);
  const warnings = useMemo(
    () => [...new Set([...draftWarnings(draft), ...serverWarnings])],
    [draft, serverWarnings],
  );
  const hasErrors = useMemo(() => draftHasErrors(draft, catalog), [draft, catalog]);

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

  const removeComponent = (id: string) =>
    setDraft((current) => ({
      ...current,
      components: current.components.filter((component) => component.id !== id),
    }));

  const loadTemplate = (templateId: string) => {
    const template = templates.items.find((item) => item.id === templateId);
    if (!template) return;
    const { draft: loaded, missing } = templateToDraft(template, catalog);
    setDraft(loaded);
    setSaveError(null);
    setServerWarnings([]);
    setNotice(
      missing.length === 0
        ? `Loaded "${template.name}". Change anything you like — nothing is saved until you press Save.`
        : `Loaded "${template.name}" without ${missing.join(', ')}: this backend does not register ${
            missing.length === 1 ? 'that rule' : 'those rules'
          }.`,
    );
  };

  const save = async (asNew: boolean) => {
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await library.save(draftToSpec(draft, catalog), asNew ? null : draft.id);
      setDraft((current) => ({ ...current, id: saved.id, name: saved.name }));
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

  const run = () => {
    if (symbols.length === 0 || hasErrors) return;
    // The inline spec, never the stored id: what runs is what is on screen,
    // including edits that have not been saved. A run pinned to an id would
    // quietly execute the last saved version instead.
    void startStrategyRun({
      strategy: draftToSpec(draft, catalog),
      symbols,
      start_date: startDate,
      end_date: endDate,
    });
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
    <div
      data-testid="strategy-builder"
      className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)]"
    >
      <div className="space-y-4">
        <Panel title="Signal catalogue" bodyClassName="max-h-[60vh] overflow-y-auto">
          {modelsStatus === 'loading' ? (
            <EmptyState icon={Hourglass} title="Loading the registry…" role="status" />
          ) : (
            <SignalCatalogue catalog={catalog} onAdd={addComponent} />
          )}
        </Panel>

        <Panel
          title="Start from a template"
          actions={
            templates.status === 'ready' ? (
              <span className={MICRO}>
                <span className="tabular-nums">{templates.items.length}</span> ready-made
              </span>
            ) : null
          }
          bodyClassName="space-y-2"
        >
          {templates.status === 'loading' ? (
            <EmptyState icon={Hourglass} title="Loading templates…" role="status" />
          ) : templates.status === 'error' ? (
            <EmptyState
              testId="templates-error"
              icon={ServerCrash}
              tone="error"
              title="Could not load the templates"
              detail={templates.error ?? undefined}
              action={
                <Button type="button" size="sm" variant="outline" onClick={templates.reload}>
                  Try again
                </Button>
              }
            />
          ) : templates.items.length === 0 ? (
            <EmptyState
              testId="templates-empty"
              icon={BookMarked}
              title="No templates offered"
              detail="This backend serves no starter strategies. Build one from the catalogue on the left instead."
            />
          ) : (
            <>
              <p className="text-[11px] text-muted-foreground">
                A worked strategy, loaded into the builder in one click. Nothing is saved until you
                press Save, so these are safe to open and take apart.
              </p>
              <ul data-testid="template-list" className="space-y-2">
                {templates.items.map((template) => (
                  <li key={template.id} className="border border-border p-2">
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-mono text-[11px]">{template.name}</p>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        aria-label={`Load the ${template.name} template`}
                        onClick={() => loadTemplate(template.id)}
                      >
                        Load
                      </Button>
                    </div>
                    {template.description ? (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {template.description}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Panel>

        <Panel
          title="Your strategies"
          actions={
            <span className={MICRO}>
              <span className="tabular-nums">{library.items.length}</span> saved
            </span>
          }
          bodyClassName="space-y-2"
        >
          {library.status === 'loading' ? (
            <EmptyState icon={Hourglass} title="Loading…" role="status" />
          ) : library.status === 'error' ? (
            <EmptyState
              testId="library-error"
              icon={ServerCrash}
              tone="error"
              title="Could not load your strategies"
              detail={library.error ?? undefined}
              action={
                <Button type="button" size="sm" variant="outline" onClick={library.reload}>
                  Try again
                </Button>
              }
            />
          ) : library.items.length === 0 ? (
            <EmptyState
              testId="library-empty"
              icon={BookMarked}
              title="Nothing saved yet"
              detail="Assemble a strategy on the right — or load a template — and press Save. Saved strategies are private to your account."
            />
          ) : (
            <ul className="divide-y divide-border" data-testid="strategy-library">
              {library.items.map((strategy) => (
                <li key={strategy.id} className="flex items-center gap-2 py-1.5">
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    aria-current={draft.id === strategy.id ? 'true' : undefined}
                    onClick={() => {
                      setDraft(specToDraft(strategy, catalog));
                      setServerWarnings(strategy.warnings ?? []);
                      setNotice(`Loaded "${strategy.name}".`);
                    }}
                  >
                    <span className="block truncate font-mono text-[11px]">{strategy.name}</span>
                    <span className="block text-[10px] text-muted-foreground">
                      <span className="tabular-nums">{strategy.components.length}</span> components ·{' '}
                      {strategy.entry_logic} in / {strategy.exit_logic} out
                    </span>
                  </button>
                  {armedDelete === strategy.id ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="border-destructive/50 text-destructive"
                      onClick={async () => {
                        setArmedDelete(null);
                        await library.remove(strategy.id);
                        setDraft((current) =>
                          current.id === strategy.id ? { ...current, id: null } : current,
                        );
                      }}
                    >
                      Confirm
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      aria-label={`Delete strategy ${strategy.name}`}
                      onClick={() => setArmedDelete(strategy.id)}
                    >
                      Delete
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="space-y-4">
        <Panel
          title="Your strategy"
          actions={
            <span className="flex items-center gap-2">
              {draft.id ? <StatusBadge tone="good">Saved</StatusBadge> : null}
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setDraft(emptyDraft());
                  setServerWarnings([]);
                  setNotice('Started an empty strategy.');
                }}
              >
                New
              </Button>
              <Button type="button" size="sm" disabled={saving} onClick={() => void save(false)}>
                {saving ? 'Saving…' : draft.id ? 'Save' : 'Save strategy'}
              </Button>
              {draft.id ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={saving}
                  onClick={() => void save(true)}
                >
                  Save as copy
                </Button>
              ) : null}
            </span>
          }
          bodyClassName="space-y-4"
        >
          <div className="space-y-1">
            <label className={MICRO} htmlFor="strategy-name">
              Name
            </label>
            <Input
              id="strategy-name"
              value={draft.name}
              placeholder="Name this strategy"
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
            />
            <p className="text-[11px] text-muted-foreground">
              Editing the name of a saved strategy and pressing Save renames it in place.
            </p>
          </div>

          {/* The single most important element on the screen: the assembled
              strategy in a sentence, regenerated on every edit. It is how a
              non-expert checks they built what they meant. */}
          <div className="border border-primary/40 bg-primary/5 p-3">
            <p className={MICRO}>In plain English</p>
            <p
              data-testid="strategy-summary"
              aria-live="polite"
              className="mt-1 text-sm leading-relaxed"
            >
              {sentence}
            </p>
          </div>

          {warnings.length > 0 ? (
            <ul data-testid="strategy-warnings" className="space-y-1">
              {warnings.map((warning) => (
                <li
                  key={warning}
                  role="alert"
                  className="flex gap-2 border border-border px-2 py-1.5 text-[11px] text-muted-foreground"
                >
                  <TriangleAlert
                    size={16}
                    strokeWidth={1.5}
                    aria-hidden="true"
                    className="mt-px shrink-0"
                  />
                  {warning}
                </li>
              ))}
            </ul>
          ) : null}

          {notice ? (
            <p role="status" data-testid="builder-notice" className="text-[11px] text-primary">
              {notice}
            </p>
          ) : null}
          {saveError ? (
            <p
              role="alert"
              data-testid="builder-save-error"
              className="border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-[11px] text-destructive"
            >
              {saveError}
            </p>
          ) : null}

          {draft.components.length === 0 ? (
            <EmptyState
              testId="builder-no-components"
              icon={FlaskConical}
              title="No components yet"
              detail="Pick a signal from the catalogue on the left and give it a role, or load one of the templates to see a finished strategy."
            />
          ) : (
            ROLE_ORDER.map((role) => {
              const components = byRole(role);
              if (components.length === 0) return null;
              return (
                <section key={role} aria-label={`${ROLE_LABELS[role]} components`} className="space-y-2">
                  <h3 className={MICRO}>
                    {ROLE_LABELS[role]}
                    <span className="ml-2 normal-case tracking-normal">
                      {ROLE_EXPLAINERS[role]}
                    </span>
                  </h3>
                  <ul className="space-y-2">
                    {components.map((component) => (
                      <StrategyComponentEditor
                        key={component.id}
                        component={component}
                        model={findModel(catalog, component.rule_name)}
                        weighted={role === 'exit' ? exitWeighted : entryWeighted}
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

        <Panel title="Combining the signals" bodyClassName="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label className={MICRO} htmlFor="entry-logic">
              Entry logic
            </label>
            <Select
              id="entry-logic"
              value={draft.entry_logic}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  entry_logic: event.target.value as CombineLogic,
                }))
              }
            >
              {COMBINE_LOGICS.map((logic) => (
                <option key={logic} value={logic}>
                  {LOGIC_LABELS[logic]}
                </option>
              ))}
            </Select>
            <p className="text-[11px] text-muted-foreground">
              {LOGIC_EXPLAINERS[draft.entry_logic]}
            </p>
          </div>

          <div className="space-y-1">
            <label className={MICRO} htmlFor="exit-logic">
              Exit logic
            </label>
            <Select
              id="exit-logic"
              value={draft.exit_logic}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  exit_logic: event.target.value as CombineLogic,
                }))
              }
            >
              {COMBINE_LOGICS.map((logic) => (
                <option key={logic} value={logic}>
                  {LOGIC_LABELS[logic]}
                </option>
              ))}
            </Select>
            <p className="text-[11px] text-muted-foreground">
              {LOGIC_EXPLAINERS[draft.exit_logic]}
            </p>
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
                  setDraft((current) => ({
                    ...current,
                    entry_threshold: Number(event.target.value),
                  }))
                }
              />
              <p className="text-[11px] text-muted-foreground">
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
                  setDraft((current) => ({
                    ...current,
                    exit_threshold: Number(event.target.value),
                  }))
                }
              />
              <p className="text-[11px] text-muted-foreground">
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
                setDraft((current) => ({
                  ...current,
                  combine_window_days: Number(event.target.value),
                }))
              }
            />
            <p className="text-[11px] text-muted-foreground">
              Components may agree within this many bars rather than only on the same bar. 1 means
              "fired today".
            </p>
          </div>
        </Panel>

        <Panel title="Execution criteria">
          <ExecutionForm
            value={draft.execution}
            onChange={(execution) => setDraft((current) => ({ ...current, execution }))}
          />
        </Panel>

        <Panel
          title="Universe & window"
          actions={
            <StatusBadge tone="idle" title="The backend serves daily bars only.">
              Daily
            </StatusBadge>
          }
          bodyClassName="space-y-3"
        >
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

          <div className="space-y-1">
            <label className={MICRO} htmlFor="strategy-symbols">
              Instruments
            </label>
            <select
              id="strategy-symbols"
              multiple
              size={5}
              className={`${fieldClasses} h-auto`}
              value={symbols}
              onChange={(event) =>
                setSymbols(Array.from(event.target.selectedOptions, (option) => option.value))
              }
            >
              {instruments.map((instrument) => (
                <option key={instrument.symbol} value={instrument.symbol}>
                  {instrument.symbol} — {instrument.name}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-muted-foreground">
              {symbols.length === 0
                ? 'Select at least one instrument to run against.'
                : `${symbols.length} selected`}
            </p>
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
            {inFlight ? (
              <Button type="button" variant="outline" onClick={cancel}>
                Cancel
              </Button>
            ) : null}
            <Button
              type="button"
              className="px-4"
              disabled={inFlight || symbols.length === 0 || hasErrors}
              onClick={run}
            >
              <Play size={16} strokeWidth={1.5} aria-hidden="true" />
              {inFlight ? 'Running…' : 'Run backtest'}
            </Button>
          </div>
          {hasErrors ? (
            <p role="alert" className="text-[11px] text-destructive">
              One or more component parameters is out of range. Fix the fields marked above before
              running.
            </p>
          ) : null}
        </Panel>

        <Panel title="Results" bodyClassName="p-0 pt-3">
          {runError ? (
            <EmptyState
              testId="builder-run-error"
              icon={ServerCrash}
              tone="error"
              title="Backtest could not start"
              detail={runError}
            />
          ) : activeRun ? (
            <RunResultsView run={activeRun} />
          ) : (
            <EmptyState
              icon={inFlight ? Hourglass : FlaskConical}
              title={inFlight ? 'Running…' : 'No results yet'}
              detail={
                inFlight
                  ? undefined
                  : 'Pick your instruments and a window above, then run the strategy. Results appear here.'
              }
              role={inFlight ? 'status' : undefined}
            />
          )}
        </Panel>
      </div>
    </div>
  );
}

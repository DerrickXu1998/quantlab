import { FlaskConical, Hourglass, ServerCrash } from 'lucide-react';
import { useMemo, useState } from 'react';
import { asCatalogModel } from '../../api/types';
import { RunConfigForm } from '../../components/RunConfigForm';
import { RunResultsView } from '../../components/RunResultsView';
import { EmptyState } from '../../components/ui/empty-state';
import { FillColumn, Measure } from '../../components/ui/layout';
import { CascadeItem } from '../../quantlab/chrome/Cascade';
import { useRuns } from '../../runs/RunsContext';
import { conceptLabel, formatCount } from '../format';
import { ResearchPanel } from '../shell/ResearchShell';
import { RuleCatalogue } from './RuleCatalogue';
import { useInstruments } from './useInstruments';

const NOTE = 'text-[11px] leading-snug text-muted-foreground';

/**
 * Test — put one rule against stored history and read what it would have done.
 *
 * This is the capability the destination already had, finally explained. It
 * replaces three panels named after tables — Models, Run, Results — with one
 * mode that says plainly what testing a rule means, lists every rule the
 * registry holds rather than only the three with materialised signals, and
 * shows each rule's category, roles, required concepts and summary, all of
 * which the registry has always sent and the old list threw away.
 *
 * The run machinery underneath is unchanged: the same `RunConfigForm`, the
 * same `RunResultsView`, the same store. A run started here is the same object
 * the Strategies destination sees, which is the point of there being one store.
 */
export function TestView(): JSX.Element {
  const {
    models,
    catalog,
    modelsStatus,
    selectedModel,
    selectModel,
    modelEntries,
    activeRun,
    inFlight,
    runError,
    start,
    cancel,
  } = useRuns();
  const { instruments, status: instrumentsStatus } = useInstruments();
  const [query, setQuery] = useState('');

  const runsByRule = useMemo(() => {
    const counts = new Map<string, number>();
    for (const entry of modelEntries) counts.set(entry.model.name, entry.runs.length);
    return counts;
  }, [modelEntries]);

  const selectedRule = useMemo(
    () => (selectedModel ? asCatalogModel(selectedModel) : null),
    [selectedModel],
  );

  const select = (name: string) => selectModel(models.find((model) => model.name === name) ?? null);

  if (modelsStatus !== 'ready') {
    return (
      <FillColumn className="gap-3 p-4">
        <ResearchPanel
          className="min-h-0 flex-1"
          title="Rules"
          purpose="Every predicate the backend can evaluate, whether or not anything has been run against it."
        >
          <div className="flex h-full flex-col justify-center">
            {modelsStatus === 'loading' ? (
              <EmptyState
                icon={Hourglass}
                role="status"
                title="Reading the rule registry"
                detail="The catalogue is served by the backend, so registering a rule there is all it takes to make it appear here."
              />
            ) : (
              <EmptyState
                testId="test-registry-error"
                icon={ServerCrash}
                tone="error"
                title="The rule registry is unreachable"
                detail="No rules could be read, so none are shown — an empty catalogue here would read as a product with no rules in it. Start the stack and reload."
              />
            )}
          </div>
        </ResearchPanel>
      </FillColumn>
    );
  }

  return (
    <FillColumn className="gap-3 p-4">
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <CascadeItem index={0} className="flex min-h-0 flex-col">
          <ResearchPanel
            className="min-h-0 flex-1"
            title="Rules"
            purpose="Reusable predicates over a price or accounting series — not trained models, so nothing here has weights or was fitted to anything."
          >
            <div className="h-full overflow-y-auto p-3" data-testid="rule-catalogue-panel">
              <RuleCatalogue
                rules={catalog}
                runsByRule={runsByRule}
                selected={selectedModel?.name ?? null}
                onSelect={select}
                query={query}
                onQuery={setQuery}
              />
            </div>
          </ResearchPanel>
        </CascadeItem>

        <CascadeItem index={1} className="flex min-h-0 flex-col gap-3">
          {/* Capped and scrolling, not `shrink-0`.
              The form's height is the rule's: an instrument list plus however
              many parameters it declares. Left unshrinkable, `accrual-reversal`
              pushed the column to 991px inside a 900px window and the results
              panel's empty state collided with the footer. It takes at most
              half the column now and scrolls past that, so the results it
              produces are always on screen beside it. */}
          <ResearchPanel
            className="max-h-[55%] shrink-0"
            title="The test"
            purpose="Choose the instruments and the window. The form is generated from the rule's own declared parameters, so it always matches what the backend accepts."
          >
            <div className="h-full space-y-3 overflow-y-auto p-3" data-testid="test-config-panel">
              {selectedRule && selectedModel ? (
                <>
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="font-display text-sm tracking-[-0.02em]">
                      {selectedRule.name}{' '}
                      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                        v{selectedRule.version}
                      </span>
                    </h3>
                    <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                      {formatCount(runsByRule.get(selectedRule.name) ?? 0)} runs recorded
                    </span>
                  </div>
                  <p className={NOTE}>{selectedRule.summary}</p>
                  <p className={NOTE}>
                    {(selectedRule.requires_facts ?? []).length > 0
                      ? `Evaluating it needs ${(selectedRule.requires_facts ?? []).map(conceptLabel).join(', ').toLowerCase()} to have been filed. Instruments that never filed them cannot trade on this rule, and are reported as uncovered in the result rather than silently skipped.`
                      : 'It reads price bars only, so every instrument with history can be tested against it.'}
                  </p>
                  {instrumentsStatus === 'error' ? (
                    <EmptyState
                      testId="test-instruments-error"
                      icon={ServerCrash}
                      tone="error"
                      title="The instrument catalogue is unreachable"
                      detail="A test needs names to run over, and none could be read."
                    />
                  ) : instrumentsStatus === 'loading' ? (
                    <EmptyState
                      icon={Hourglass}
                      role="status"
                      title="Loading the instrument catalogue"
                      detail="The symbols a test can run over are read from the warehouse."
                    />
                  ) : (
                    <Measure size="base" center={false}>
                      <RunConfigForm
                        model={selectedModel}
                        instruments={instruments}
                        running={inFlight}
                        onRun={(body) => void start(body)}
                        onCancel={cancel}
                      />
                    </Measure>
                  )}
                  {runError ? (
                    <p role="alert" className="text-xs text-destructive">
                      {runError}
                    </p>
                  ) : null}
                </>
              ) : (
                <EmptyState
                  testId="test-no-rule"
                  icon={FlaskConical}
                  title="No rule chosen"
                  detail="Pick one on the left. Everything a test needs — its parameters, the concepts it reads, the history it requires — comes from that rule's own registry entry."
                />
              )}
            </div>
          </ResearchPanel>

          <ResearchPanel
            className="min-h-0 flex-1"
            title="What it would have done"
            purpose="The signals and trades the rule would have produced over stored history. No order is placed, no money moves, and nothing in the warehouse changes."
          >
            <div className="flex h-full min-h-0 flex-col">
              {activeRun ? (
                <div className="min-h-0 flex-1" data-testid="test-results">
                  <RunResultsView run={activeRun} />
                </div>
              ) : (
                <EmptyState
                  testId={inFlight ? 'test-running' : 'test-no-run'}
                  className="my-auto"
                  icon={inFlight ? Hourglass : FlaskConical}
                  role={inFlight ? 'status' : undefined}
                  title={inFlight ? 'Running the test' : 'No test run yet'}
                  detail={
                    inFlight
                      ? 'Replaying the rule over the chosen window, bar by bar, against stored history.'
                      : 'Choose a rule, a set of instruments and a window, then run. What appears here is what the rule would have signalled — it is a reading of the past, not a prediction and not a trade.'
                  }
                />
              )}
            </div>
          </ResearchPanel>
        </CascadeItem>
      </div>
    </FillColumn>
  );
}

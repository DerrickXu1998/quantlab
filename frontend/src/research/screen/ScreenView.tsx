import { Ban, Hourglass, ScanSearch, SearchX, ServerCrash } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { ScreenMetric, ScreenMetricCoverage } from '../../api/types';
import { SCREEN_METRICS } from '../../api/types';
import { Button } from '../../components/ui/button';
import { EmptyState } from '../../components/ui/empty-state';
import { FillColumn, ScrollRegion } from '../../components/ui/layout';
import { CascadeItem } from '../../quantlab/chrome/Cascade';
import {
  formatCount,
  METRIC_FORMAT,
  metricSource,
  requirementLabel,
  TIINGO_METRICS,
} from '../format';
import { ResearchPanel } from '../shell/ResearchShell';
import { CoverageLine, ExclusionLedger } from './Coverage';
import { ScreenControls } from './ScreenControls';
import { ScreenTable } from './ScreenTable';
import { describeConstraint, newDraft, readDrafts, type ConstraintDraft } from './constraints';
import { useUniverses, type UniversesState } from '../../api/UniversesProvider';
import { useScreen, type ScreenQuery } from './useScreen';

export interface ScreenViewProps {
  /** Hands the chosen name to the shell, which walks the user over to Company. */
  onSelectSymbol: (symbol: string) => void;
}

/** Every ratio is asked for, so coverage comes back for every ratio. */
const ALL_METRICS: ScreenMetric[] = [...SCREEN_METRICS];

/**
 * The columns shown before the reader picks their own: every metric the
 * answer could measure for at least one name. On the US list that is Tiingo's
 * published figures; where SEC concepts are filed, the computed ratios join
 * them. A column that is a dash in every row tells the reader nothing the
 * coverage lines do not already say. Every metric is still fetched, so
 * changing columns never re-runs the screen.
 */
export function autoColumns(coverage: readonly ScreenMetricCoverage[] | undefined): ScreenMetric[] {
  const measured = new Set(
    (coverage ?? []).filter((entry) => entry.measured > 0).map((entry) => entry.metric),
  );
  const all = SCREEN_METRICS.filter((metric) => measured.has(metric));
  if (all.length <= MAX_AUTO_COLUMNS) return all;
  // More than a table can carry legibly: start from the figures a valuation
  // screen is usually read by. Every other measured metric is one tick away.
  const preferred = all.filter((metric) => PREFERRED_COLUMNS.has(metric));
  return preferred.length > 0 ? preferred : all.slice(0, MAX_AUTO_COLUMNS);
}

const MAX_AUTO_COLUMNS = 8;

const PREFERRED_COLUMNS: ReadonlySet<ScreenMetric> = new Set<ScreenMetric>([
  'pe',
  'pb',
  'roe',
  'market_cap',
  'pe_ratio',
  'pb_ratio',
  'peg_ratio_1y',
  'roe_reported',
  'gross_margin_reported',
  'debt_equity_reported',
  'piotroski_f_score',
]);

/** Shown columns: the chosen ones, plus whatever the answer was constrained or ranked by. */
export function visibleMetrics(
  columns: readonly ScreenMetric[],
  answered: { constraints: { metric: ScreenMetric }[]; sortBy: ScreenMetric | null } | null,
): ScreenMetric[] {
  const wanted = new Set<ScreenMetric>(columns);
  for (const constraint of answered?.constraints ?? []) wanted.add(constraint.metric);
  if (answered?.sortBy) wanted.add(answered.sortBy);
  return SCREEN_METRICS.filter((metric) => wanted.has(metric));
}

/**
 * Screen — narrow a universe by what companies actually filed.
 *
 * The mode answers one question: *which names in this list clear these
 * numbers, as the accounts stood on this date*. Two things make it honest
 * rather than merely useful, and both are on screen at all times:
 *
 *   1. every constraint states its own coverage, because coverage is not
 *      uniform — gross profit is filed by 237 names against revenue's 376
 *      (docs/RESEARCH.md §2);
 *   2. the two exclusions are reported separately, because "measured and did
 *      not qualify" and "never measured" are opposite findings.
 *
 * Collapsing either is how a screen quietly lies.
 */
export function ScreenView({ onSelectSymbol }: ScreenViewProps): JSX.Element {
  const universes = useUniverses();
  const { result, status, message, answered, run } = useScreen();

  const [universe, setUniverse] = useState('');
  const [asOf, setAsOf] = useState('');
  const [limit, setLimit] = useState(50);
  const [drafts, setDrafts] = useState<ConstraintDraft[]>([]);
  const [sortBy, setSortBy] = useState<ScreenMetric | null>(null);
  const [descending, setDescending] = useState(false);
  // Null until the reader ticks a box: until then the columns follow coverage.
  const [chosenColumns, setColumns] = useState<ScreenMetric[] | null>(null);
  const columns = chosenColumns ?? autoColumns(result?.coverage);

  // Default to the first published universe rather than a hardcoded name: the
  // one real list is `liquid-500-ftse-core`, but naming it here would make the
  // UI lie on any deployment that publishes a different one.
  useEffect(() => {
    if (universe === '' && universes.universes.length > 0) {
      setUniverse(universes.universes[0].name);
    }
  }, [universe, universes.universes]);

  const { constraints, errors } = useMemo(() => readDrafts(drafts), [drafts]);
  const invalid = Object.keys(errors).length > 0;

  const query = useMemo<ScreenQuery>(
    () => ({
      universe,
      constraints,
      metrics: ALL_METRICS,
      asOf: asOf === '' ? null : asOf,
      sortBy,
      descending,
      limit,
    }),
    [universe, constraints, asOf, sortBy, descending, limit],
  );

  const stale = answered !== null && JSON.stringify(answered) !== JSON.stringify(query);

  const coverageByMetric = useMemo(() => {
    const map = new Map<ScreenMetric, ScreenMetricCoverage>();
    for (const entry of result?.coverage ?? []) map.set(entry.metric, entry);
    return map;
  }, [result]);

  const addConstraint = () => {
    const used = new Set(drafts.map((draft) => draft.metric));
    // Once a screen has run, the first metric it could actually measure: a
    // constraint on a ratio nobody has is a constraint that empties the table.
    const next =
      autoColumns(result?.coverage).find((metric) => !used.has(metric)) ??
      SCREEN_METRICS.find((metric) => !used.has(metric)) ??
      SCREEN_METRICS[0];
    setDrafts((current) => [...current, newDraft(next)]);
  };

  const changeConstraint = (id: string, patch: Partial<ConstraintDraft>) =>
    setDrafts((current) =>
      current.map((draft) => (draft.id === id ? { ...draft, ...patch } : draft)),
    );

  const removeConstraint = (id: string) =>
    setDrafts((current) => current.filter((draft) => draft.id !== id));

  // Re-ranking is a click on an answer that is already on screen, so it runs
  // at once. Editing the question is not, so it waits for Run.
  const sortByMetric = (metric: ScreenMetric) => {
    const nextDescending = sortBy === metric ? !descending : true;
    setSortBy(metric);
    setDescending(nextDescending);
    run({ ...query, sortBy: metric, descending: nextDescending });
  };

  if (universes.status !== 'ready' || universes.universes.length === 0) {
    return <Unavailable universes={universes} />;
  }

  return (
    <FillColumn className="gap-3 p-4">
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[21rem_minmax(0,1fr)]">
        <CascadeItem index={0} className="flex min-h-0 flex-col">
          <ResearchPanel
            className="min-h-0 flex-1"
            title="The question"
            purpose="Pick a list, set the bounds, run. Nothing is computed until you press Run."
          >
            <div className="h-full overflow-y-auto p-3" data-testid="screen-question-panel">
              <ScreenControls
                universes={universes.universes}
                universe={universe}
                onUniverse={setUniverse}
                asOf={asOf}
                onAsOf={setAsOf}
                limit={limit}
                onLimit={setLimit}
                drafts={drafts}
                errors={errors}
                onAddConstraint={addConstraint}
                onChangeConstraint={changeConstraint}
                onRemoveConstraint={removeConstraint}
                coverageFor={(metric) => coverageByMetric.get(metric) ?? null}
                onRun={() => run(query)}
                running={status === 'running'}
                blocked={invalid || universe === ''}
                stale={stale}
              />
            </div>
          </ResearchPanel>
        </CascadeItem>

        <CascadeItem index={1} className="flex min-h-0 flex-col">
          <ResearchPanel
            className="min-h-0 flex-1"
            title="What qualified"
            purpose="The names that cleared every bound, ranked — beside how many were never measured at all."
            actions={
              result ? (
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                  as filed on {result.as_of}
                </span>
              ) : null
            }
          >
            <div className="flex h-full min-h-0 flex-col" data-testid="screen-results-panel">
              <Results
                status={status}
                message={message}
                result={result}
                answered={answered}
                universe={universe}
                onRetry={() => run(query)}
                onSelectSymbol={onSelectSymbol}
                onSort={sortByMetric}
                columns={columns}
                onColumns={setColumns}
              />
            </div>
          </ResearchPanel>
        </CascadeItem>
      </div>
    </FillColumn>
  );
}

/**
 * The metrics no member could be measured on, in one sentence.
 *
 * Still stated -- a reader about to constrain on P/E must learn first that
 * nobody here has the concepts it needs -- but as one line, not seven bars at
 * zero pushing the answer below the fold.
 */
function Unmeasurable({ coverage }: { coverage: ScreenMetricCoverage[] }) {
  const none = coverage.filter((entry) => entry.measured === 0);
  if (none.length === 0) return null;
  const needs = [...new Set(none.flatMap((entry) => entry.requires ?? []))].map(requirementLabel);
  return (
    <p data-testid="coverage-unmeasurable" className="text-xs text-muted-foreground">
      Measured for no name in this list:{' '}
      <span className="text-foreground">
        {none.map((entry) => METRIC_FORMAT[entry.metric].label).join(', ')}
      </span>
      {needs.length > 0 ? ` — they need ${needs.join(', ')}, which no member has filed.` : '.'}
    </p>
  );
}

/**
 * Which figures the table shows, chosen without re-running the screen.
 *
 * Every metric was fetched, so this is a view over the answer already on
 * screen. A metric the answer was constrained or ranked by stays shown and
 * cannot be unticked: hiding the column a ranking is ordered by would leave
 * the order unexplained.
 */
function ColumnChooser({
  columns,
  pinned,
  onColumns,
}: {
  columns: ScreenMetric[];
  pinned: ScreenMetric[];
  onColumns: (columns: ScreenMetric[]) => void;
}) {
  const chosen = new Set<ScreenMetric>(columns);
  const locked = new Set<ScreenMetric>(pinned.filter((metric) => !chosen.has(metric)));
  const toggle = (metric: ScreenMetric) =>
    onColumns(
      chosen.has(metric)
        ? columns.filter((item) => item !== metric)
        : SCREEN_METRICS.filter((item) => chosen.has(item) || item === metric),
    );
  const group = (title: string, metrics: readonly ScreenMetric[]) => (
    <fieldset className="space-y-1">
      <legend className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {title}
      </legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {metrics.map((metric) => (
          <label key={metric} className="inline-flex items-center gap-1.5 text-xs">
            <input
              type="checkbox"
              checked={chosen.has(metric) || locked.has(metric)}
              disabled={locked.has(metric)}
              onChange={() => toggle(metric)}
              data-testid={`column-${metric}`}
            />
            {METRIC_FORMAT[metric].label}
          </label>
        ))}
      </div>
    </fieldset>
  );
  return (
    <details className="border-t border-border pt-3" data-testid="screen-columns">
      <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground hover:text-foreground">
        Columns ({pinned.length} shown)
      </summary>
      <div className="mt-2 space-y-2">
        {group('Published by Tiingo', TIINGO_METRICS)}
        {group(
          'Computed from filed accounts',
          SCREEN_METRICS.filter((metric) => metricSource(metric) === 'filed'),
        )}
      </div>
    </details>
  );
}

/**
 * The four ways there is nothing to screen within, kept apart.
 *
 * A 404 says this deployment does not serve universes, any other failure says
 * the stack is down, and an empty list says the warehouse holds no membership
 * lists. Three different next actions, so three different screens — and none
 * of them is a bare spinner.
 */
function Unavailable({ universes }: { universes: UniversesState }) {
  const state = (() => {
    if (universes.status === 'loading') {
      return {
        testId: undefined,
        icon: Hourglass,
        tone: 'neutral' as const,
        role: 'status' as const,
        title: 'Reading the published universes',
        detail: 'A screen runs inside a named list, so the lists load first.',
        retry: false,
      };
    }
    if (universes.status === 'unsupported') {
      return {
        testId: 'screen-unsupported',
        icon: Ban,
        tone: 'neutral' as const,
        role: undefined,
        title: 'Screening is not served here',
        detail:
          'This backend does not publish universes, so there is no list to screen within. Nothing is wrong with your filters — the route is simply not on this deployment.',
        retry: true,
      };
    }
    if (universes.status === 'error') {
      return {
        testId: 'screen-universes-error',
        icon: ServerCrash,
        tone: 'error' as const,
        role: undefined,
        title: 'The universe list is unreachable',
        detail: `${universes.message ?? 'The universe list could not be read.'} The stack may be down; nothing has been shown in its place.`,
        retry: true,
      };
    }
    return {
      testId: 'screen-no-universes',
      icon: SearchX,
      tone: 'neutral' as const,
      role: undefined,
      title: 'No universes published',
      detail:
        'The backend serves the route but holds no membership lists. A screen needs one — the index that makes it sub-second is keyed by instrument.',
      retry: true,
    };
  })();

  return (
    <FillColumn className="gap-3 p-4">
      <ResearchPanel
        className="min-h-0 flex-1"
        title="Screen"
        purpose="Narrow a list of companies by the ratios their filed accounts support."
      >
        <div className="flex h-full flex-col justify-center">
          <EmptyState
            testId={state.testId}
            icon={state.icon}
            tone={state.tone}
            role={state.role}
            title={state.title}
            detail={state.detail}
            action={
              state.retry ? (
                <Button variant="outline" size="sm" className="mt-2" onClick={universes.reload}>
                  Try again
                </Button>
              ) : undefined
            }
          />
        </div>
      </ResearchPanel>
    </FillColumn>
  );
}

function Results({
  status,
  message,
  result,
  answered,
  universe,
  onRetry,
  onSelectSymbol,
  onSort,
  columns,
  onColumns,
}: {
  status: ReturnType<typeof useScreen>['status'];
  message: string | null;
  result: ReturnType<typeof useScreen>['result'];
  answered: ScreenQuery | null;
  universe: string;
  onRetry: () => void;
  onSelectSymbol: (symbol: string) => void;
  onSort: (metric: ScreenMetric) => void;
  columns: ScreenMetric[];
  onColumns: (columns: ScreenMetric[]) => void;
}) {
  if (status === 'idle') {
    return (
      <EmptyState
        testId="screen-idle"
        className="my-auto"
        icon={ScanSearch}
        title="No screen run yet"
        detail={`Nothing has been asked of ${universe || 'this universe'}. Set the bounds on the left and press Run — the result is a ranked table, and every row opens as a company.`}
      />
    );
  }

  if (status === 'running' && !result) {
    return (
      <EmptyState
        testId="screen-running"
        className="my-auto"
        icon={Hourglass}
        role="status"
        title="Screening the universe"
        detail={`Reading the filed accounts for every member of ${universe}. A few seconds — it is a full pass over the filings index, not a cached answer.`}
      />
    );
  }

  if (status === 'unsupported') {
    return (
      <EmptyState
        testId="screen-route-unsupported"
        className="my-auto"
        icon={Ban}
        title="The screener is not served here"
        detail="This backend answers the universe list but not the screen itself. That is a deployment that predates the route — not a fault, and not an empty result."
      />
    );
  }

  if (status === 'error') {
    return (
      <EmptyState
        testId="screen-error"
        className="my-auto"
        icon={ServerCrash}
        tone="error"
        title="The screen could not be run"
        detail={`${message ?? 'The screener is unreachable.'} Nothing has been shown in its place — an empty table here would read as a result.`}
        action={
          <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
            Try again
          </Button>
        }
      />
    );
  }

  if (!result || !answered) return <></>;

  const shown = visibleMetrics(columns, answered);

  return (
    <>
      <div className="shrink-0 space-y-3 border-b border-border p-3">
        <p className="text-xs leading-snug text-muted-foreground" data-testid="screen-question">
          {answered.constraints.length === 0
            ? `${formatCount(result.universe_size)} names in ${result.universe}, unconstrained.`
            : `${result.universe} where ${answered.constraints.map(describeConstraint).join(' and ')}.`}
        </p>

        <ExclusionLedger result={result} />

        <ColumnChooser columns={columns} pinned={shown} onColumns={onColumns} />

        {/*
          Coverage for every ratio on offer, not only the constrained ones. A
          reader deciding what to constrain next needs to know that gross
          margin can only be computed for 237 of 598 names *before* they
          constrain on it and watch the table collapse.
        */}
        {result.coverage.length > 0 ? (
          <div className="space-y-2 border-t border-border pt-3">
            <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              What could be measured at all
            </p>
            <div className="grid grid-cols-1 gap-x-8 gap-y-2 md:grid-cols-2 xl:grid-cols-3">
              {result.coverage
                .filter((entry) => entry.measured > 0)
                .map((entry) => (
                  <CoverageLine key={entry.metric} metric={entry.metric} coverage={entry} />
                ))}
            </div>
            <Unmeasurable coverage={result.coverage} />
          </div>
        ) : null}
      </div>

      {result.rows.length === 0 ? (
        <EmptyState
          testId="screen-no-matches"
          className="my-auto"
          icon={SearchX}
          title="No name qualified"
          detail={`Of ${formatCount(result.universe_size)}, ${formatCount(result.excluded_by_constraint)} were measured and failed, and ${formatCount(result.excluded_unmeasured)} were never measured at all. Loosening the bounds only reaches the first group.`}
        />
      ) : (
        <ScrollRegion testId="screen-rows">
          <ScreenTable
            result={result}
            metrics={shown}
            descending={answered.descending}
            busy={status === 'running'}
            onSelectSymbol={onSelectSymbol}
            onSort={onSort}
          />
        </ScrollRegion>
      )}
    </>
  );
}

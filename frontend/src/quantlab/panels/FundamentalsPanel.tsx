import { Hourglass, Landmark, ServerCrash } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useDataset } from '../../api/DatasetProvider';
import { Button } from '../../components/ui/button';
import { EmptyState } from '../../components/ui/empty-state';
import { Numeric } from '../../components/ui/numeric';
import { StatusBadge } from '../../components/ui/status-badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { ValueLineChart, type ValuePoint } from '../charts/ValueLineChart';
import {
  getFundamentalSeries,
  isFact,
  isSeriesPoint,
  listFundamentalConcepts,
  type FundamentalConcept,
  type FundamentalSeries,
} from '../data/fundamentals';
import { Panel } from '../chrome/Panel';

type LoadState<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string };

/** Same discipline as useDailyBars: a failed read is an error with a retry,
 *  never an endless loading state. */
function useFetch<T>(load: () => Promise<T>, deps: unknown[]): LoadState<T> & { retry: () => void } {
  const [state, setState] = useState<LoadState<T>>({ status: 'loading' });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    load()
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: 'error',
            message: error instanceof Error ? error.message : 'request failed',
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // The caller's deps key the fetch; `load` is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { ...state, retry: () => setNonce((n) => n + 1) };
}

function LoadFailure({
  testId,
  title,
  detail,
  onRetry,
}: {
  testId: string;
  title: string;
  detail: string;
  onRetry: () => void;
}) {
  return (
    <EmptyState
      testId={testId}
      icon={ServerCrash}
      tone="error"
      title={title}
      detail={detail}
      action={
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      }
    />
  );
}

/** The chart and the filings table for one selected concept. */
function ConceptSeries({
  symbol,
  concept,
}: {
  symbol: string;
  concept: FundamentalConcept;
}) {
  const [transform, setTransform] = useState<'raw' | 'yoy_growth'>('raw');

  useEffect(() => {
    setTransform('raw');
  }, [symbol, concept]);

  const series = useFetch<FundamentalSeries>(
    () => getFundamentalSeries(symbol, concept.concept, transform),
    [symbol, concept, transform],
  );
  // The filings table always reads raw_facts: filing-level rows are where a
  // restatement shows up as two rows for one period.
  const facts = useFetch<FundamentalSeries>(
    () => getFundamentalSeries(symbol, concept.concept, 'raw_facts'),
    [symbol, concept],
  );

  const points: ValuePoint[] = useMemo(() => {
    if (series.status !== 'ready') return [];
    return series.data.items
      .filter(isSeriesPoint)
      .map((point) => ({ date: point.date, value: point.value }));
  }, [series]);

  const filings = useMemo(() => {
    if (facts.status !== 'ready') return [];
    return facts.data.items.filter(isFact);
  }, [facts]);

  return (
    <div className="mt-3 space-y-3" data-testid="fundamentals-series">
      <div className="flex items-center justify-between gap-2">
        <div
          role="group"
          aria-label="Transform"
          className="grid w-fit grid-cols-2 gap-px rounded-sm border border-border bg-border"
        >
          {(
            [
              { id: 'raw', label: 'As filed' },
              { id: 'yoy_growth', label: 'YoY growth' },
            ] as const
          ).map((option) => (
            <button
              key={option.id}
              type="button"
              aria-pressed={transform === option.id}
              onClick={() => setTransform(option.id)}
              className={`px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-primary ${
                transform === option.id
                  ? 'bg-primary/10 text-primary'
                  : 'bg-card text-muted-foreground hover:text-foreground'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        {series.status === 'ready' && series.data.point_in_time ? (
          <StatusBadge
            tone="idle"
            testId="pit-badge"
            title="Every value is visible only from its filed_at — the series cannot look ahead."
          >
            Point-in-time
          </StatusBadge>
        ) : null}
      </div>

      {series.status === 'error' ? (
        <LoadFailure
          testId="fundamentals-series-error"
          title="Series unavailable"
          detail={series.message}
          onRetry={series.retry}
        />
      ) : series.status !== 'ready' ? (
        <EmptyState icon={Hourglass} title="Loading series…" role="status" />
      ) : points.length === 0 ? (
        <EmptyState
          testId="fundamentals-series-empty"
          icon={Landmark}
          title="Nothing filed"
          detail={`No ${transform === 'yoy_growth' ? 'year-over-year' : 'as-filed'} points for ${concept.concept} on ${symbol}.`}
        />
      ) : (
        <>
          <ValueLineChart
            points={points}
            step={transform === 'raw'}
            format={transform === 'yoy_growth' ? 'percent' : 'compact'}
            testId="fundamentals-chart"
          />
          <p data-testid="fundamentals-provenance" className="text-[10px] text-muted-foreground">
            {series.data.provenance}
          </p>
        </>
      )}

      {facts.status === 'ready' && filings.length > 0 ? (
        <div className="max-h-56 overflow-y-auto rounded-sm border border-border">
          <Table data-testid="fundamentals-filings">
            <TableHeader>
              <TableRow>
                <TableHead>Filed</TableHead>
                <TableHead>Period end</TableHead>
                <TableHead className="text-right">Value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filings.map((fact, index) => (
                <TableRow key={`${fact.filed_at}-${fact.period_end}-${index}`}>
                  <TableCell className="font-mono text-xs tabular-nums">{fact.filed_at}</TableCell>
                  <TableCell className="font-mono text-xs tabular-nums text-muted-foreground">
                    {fact.period_end}
                  </TableCell>
                  <TableCell className="text-right">
                    <Numeric value={fact.value} format="compact" className="text-xs" />
                    <span className="ml-1 text-[10px] text-muted-foreground">{fact.unit}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}

/**
 * One instrument's fundamentals: the concept catalog as chips, then the
 * selected concept as a point-in-time step line with its filing rows beneath.
 * The provenance string ships in the payload and is shown with the numbers —
 * the disclosure travels with the data, not with UI copy.
 */
export function FundamentalsPanel({ symbol }: { symbol: string }) {
  const dataset = useDataset();
  const concepts = useFetch(() => listFundamentalConcepts(symbol), [symbol]);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    setSelected(null);
  }, [symbol]);

  const selectedConcept =
    concepts.status === 'ready'
      ? (concepts.data.items.find((item) => item.concept === selected) ?? null)
      : null;

  return (
    <Panel title={`Fundamentals — ${symbol}`} className="border-0" bodyClassName="p-3">
      {concepts.status === 'error' ? (
        <LoadFailure
          testId="fundamentals-error"
          title="Fundamentals unavailable"
          detail={concepts.message}
          onRetry={concepts.retry}
        />
      ) : concepts.status !== 'ready' ? (
        <EmptyState icon={Hourglass} title="Loading fundamentals…" role="status" />
      ) : concepts.data.items.length === 0 ? (
        dataset.status === 'ready' && dataset.health.dataset !== 'warehouse' ? (
          <EmptyState
            testId="fundamentals-demo-empty"
            icon={Landmark}
            title="No fundamentals in the demo dataset"
            detail="The synthetic demo dataset carries no fundamentals; run against the warehouse."
          />
        ) : (
          <EmptyState
            testId="fundamentals-empty"
            icon={Landmark}
            title="No fundamentals filed"
            detail={`The active dataset stores no fundamentals for ${symbol}.`}
          />
        )
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5" data-testid="fundamental-concepts">
            {concepts.data.items.map((item) => (
              <button
                key={`${item.concept}@${item.provider}`}
                type="button"
                aria-pressed={selected === item.concept}
                onClick={() => setSelected(item.concept)}
                title={`${item.provider} · ${item.first_filed} → ${item.last_filed}`}
                className={`flex items-center gap-1.5 rounded-sm border px-2 py-1 transition-colors focus-visible:outline-none focus-visible:border-primary ${
                  selected === item.concept
                    ? 'border-primary/50 bg-primary/10 text-primary'
                    : 'border-border bg-card text-foreground hover:bg-accent/40'
                }`}
              >
                <span className="font-mono text-[11px]">{item.concept}</span>
                <span className="font-mono text-[9px] text-muted-foreground">
                  {item.fact_count}
                </span>
                {item.derived ? (
                  <StatusBadge tone="idle" title="Computed at read time from stored concepts; never stored itself.">
                    Derived
                  </StatusBadge>
                ) : null}
              </button>
            ))}
          </div>
          {selectedConcept ? (
            <ConceptSeries symbol={symbol} concept={selectedConcept} />
          ) : (
            <p className="mt-3 text-[11px] text-muted-foreground">
              Select a concept to see its point-in-time series and filings.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}

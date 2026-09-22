import { FileClock, Hourglass, ScanSearch, TriangleAlert } from 'lucide-react';
import { useMemo } from 'react';
import type { CatalogModel, FundamentalsCoverage } from '../api/types';
import { Button } from '../components/ui/button';
import { StatusBadge } from '../components/ui/status-badge';
import {
  conceptCoverage,
  conceptLabel,
  coverageGap,
  coverageSentence,
  fundamentalComponents,
  requiredConcepts,
  windowMissesCoverage,
} from './fundamentals';
import type { Draft } from './strategyModel';
import type { FundamentalsStatus } from './useFundamentals';

const MICRO = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

/**
 * What the strategy cannot see, said before the run rather than after it.
 *
 * FUNDAMENTALS §5.1 is the argument for this component existing: 64 of 644
 * instruments have no filings, and a strategy with a fundamental filter over
 * those names does not "find no trades" — it *cannot* trade. In a result the
 * two are indistinguishable, so the only place the difference can be stated is
 * here, while the user is still choosing.
 *
 * It is not painted with `--destructive`. Red on this surface means a loss or
 * a drawdown; a gate that is shut for want of a filing is neither, and
 * spending the loss colour on it would blunt the one place red has to mean
 * something. The accent and a triangle carry it instead.
 */
export function CoverageWarning({
  draft,
  catalog,
  symbols,
  startDate,
  endDate,
  coverage,
  status,
  message,
  onReload,
  onInspect,
}: {
  draft: Draft;
  catalog: CatalogModel[];
  /** The instruments currently selected to run against. */
  symbols: string[];
  startDate: string;
  endDate: string;
  coverage: FundamentalsCoverage | null;
  status: FundamentalsStatus;
  message: string | null;
  onReload: () => void;
  /** Opens the point-in-time inspector on a name that cannot trade. */
  onInspect: (symbol: string) => void;
}) {
  const components = useMemo(
    () => fundamentalComponents(draft, catalog),
    [draft, catalog],
  );
  const concepts = useMemo(() => requiredConcepts(draft, catalog), [draft, catalog]);
  const gap = useMemo(
    () => coverageGap(symbols, concepts, coverage),
    [symbols, concepts, coverage],
  );

  // §5.2: a concept whose filings begin after the run window ends can never be
  // true inside it. The window comes from the server's own coverage row, never
  // from a date written into this file.
  const starved = useMemo(
    () =>
      concepts.filter((concept) =>
        windowMissesCoverage(conceptCoverage(coverage, concept), startDate, endDate),
      ),
    [concepts, coverage, startDate, endDate],
  );

  // No fundamental component, nothing to say. The notice appears the moment
  // one is added and disappears the moment the last one is removed.
  if (components.length === 0) return null;

  const conceptList = concepts.map(conceptLabel).join(', ');

  return (
    <section
      data-testid="fundamental-coverage"
      aria-label="Fundamental coverage"
      className="space-y-2 border border-primary/50 bg-primary/5 p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <p className={MICRO}>
          <FileClock
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="mr-1.5 inline align-text-bottom"
          />
          Fundamental coverage
        </p>
        {coverage ? (
          <StatusBadge
            tone="idle"
            title="Instruments in the catalogue with at least one filed fact."
          >
            <span className="tabular-nums">
              {coverage.instruments_with_facts}/{coverage.instruments_total}
            </span>{' '}
            covered
          </StatusBadge>
        ) : null}
      </div>

      <p className="text-[11px] text-muted-foreground">
        {components.length === 1 ? 'This component reads' : 'These components read'}{' '}
        <span className="text-foreground">{conceptList || 'filed fundamentals'}</span>. A name with
        no filing has no ratio, so its gate is shut — never "cheap".
      </p>

      {status === 'loading' ? (
        <p role="status" data-testid="coverage-loading" className={MICRO}>
          <Hourglass
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="mr-1.5 inline align-text-bottom"
          />
          Checking coverage…
        </p>
      ) : status === 'unsupported' ? (
        <p role="alert" data-testid="coverage-unsupported" className="text-xs">
          This backend does not serve fundamentals coverage, so this screen cannot tell you which of
          your instruments have filings. Run it and the result will not distinguish "found nothing"
          from "could never trade".
        </p>
      ) : status === 'error' ? (
        <div data-testid="coverage-error" role="alert" className="space-y-2">
          <p className="text-xs">
            Coverage could not be read{message ? `: ${message}` : '.'} Until it can, treat an empty
            result as unexplained rather than as a verdict on the strategy.
          </p>
          <Button type="button" size="sm" variant="outline" onClick={onReload}>
            Try again
          </Button>
        </div>
      ) : symbols.length === 0 ? (
        <p data-testid="coverage-no-selection" className="text-xs text-muted-foreground">
          Select the instruments to run against and this will say how many of them have the filings
          this strategy needs.
        </p>
      ) : gap === null ? (
        <p role="alert" data-testid="coverage-indeterminate" className="text-xs">
          The server reported totals but not which instruments have filings, so your selection could
          not be checked name by name.
        </p>
      ) : gap.missing.length === 0 ? (
        <p data-testid="coverage-clear" className="text-xs">
          {coverageSentence(gap)}
        </p>
      ) : (
        <div data-testid="coverage-gap" role="alert" className="space-y-2">
          <p className="flex gap-2 text-sm leading-relaxed">
            <TriangleAlert
              size={16}
              strokeWidth={1.5}
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-primary"
            />
            <span>{coverageSentence(gap)}</span>
          </p>
          <ul className="flex flex-wrap gap-1" data-testid="coverage-missing-symbols">
            {gap.missing.map((symbol) => (
              <li key={symbol}>
                <button
                  type="button"
                  onClick={() => onInspect(symbol)}
                  title={`Open ${symbol} in the point-in-time inspector`}
                  className="border border-border px-1.5 py-px font-mono text-[10px] tracking-[0.06em] text-muted-foreground transition-colors hover:text-foreground"
                >
                  {symbol}
                </button>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-muted-foreground">
            {gap.basis === 'concept'
              ? `Checked concept by concept: each of these is missing at least one of ${conceptList}.`
              : 'Checked against names with any filing at all — a name counted as covered may still be missing one of these concepts, so this is a floor.'}
          </p>
        </div>
      )}

      {starved.length > 0 ? (
        <ul data-testid="coverage-window-warnings" className="space-y-1">
          {starved.map((concept) => {
            const entry = conceptCoverage(coverage, concept);
            return (
              <li key={concept} role="alert" className="flex gap-2 border border-border p-2 text-[11px]">
                <TriangleAlert
                  size={16}
                  strokeWidth={1.5}
                  aria-hidden="true"
                  className="mt-px shrink-0 text-primary"
                />
                <span>
                  <span className="font-mono">{conceptLabel(concept)}</span> is only filed{' '}
                  <span className="font-mono tabular-nums">
                    {entry?.first_filed} → {entry?.last_filed}
                  </span>
                  , which is outside your window of{' '}
                  <span className="font-mono tabular-nums">
                    {startDate} → {endDate}
                  </span>
                  . Nothing will match: the gate is never open inside this run.
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}

      {symbols.length > 0 ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onInspect(gap?.missing[0] ?? symbols[0])}
        >
          <ScanSearch size={16} strokeWidth={1.5} aria-hidden="true" />
          What did it know, and when?
        </Button>
      ) : null}
    </section>
  );
}

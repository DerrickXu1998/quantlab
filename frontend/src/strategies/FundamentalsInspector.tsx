import { Database, FileClock, Hourglass, ScanSearch, ServerCrash } from 'lucide-react';
import { useMemo } from 'react';
import type { Instrument } from '../api/client';
import type { FundamentalFact } from '../api/types';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { fieldClasses, Select } from '../components/ui/field';
import { FillColumn, Measure, ScrollRegion, StatGrid } from '../components/ui/layout';
import { Numeric } from '../components/ui/numeric';
import { StatusBadge } from '../components/ui/status-badge';
import { Panel } from '../quantlab/chrome/Panel';
import {
  conceptLabel,
  groupByConcept,
  isForwardDated,
  restatementKind,
  type ConceptHistory,
} from './fundamentals';
import { useInstrumentFacts } from './useFundamentals';

const MICRO = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

/**
 * A figure's magnitude decides its format, nothing else.
 *
 * Revenue is 67,060,000,000 and a margin is 0.18; rendering both with two
 * decimals makes one unreadable and the other zero. This is formatting, not
 * analysis — the value is printed exactly as served, only grouped.
 */
function factFormat(value: number): 'integer' | 'price' {
  return Math.abs(value) >= 1000 ? 'integer' : 'price';
}

function Stat({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div title={title}>
      <p className={MICRO}>{label}</p>
      <p className="mt-0.5 text-sm">{children}</p>
    </div>
  );
}

/** The period a row describes, which is never the same as when it was knowable. */
function Period({ fact }: { fact: FundamentalFact }) {
  return (
    <span className="font-mono text-[11px] tabular-nums">
      {fact.period_start ? `${fact.period_start} → ` : ''}
      {fact.period_end}
    </span>
  );
}

function FactValue({ fact }: { fact: FundamentalFact }) {
  return (
    <span className="whitespace-nowrap">
      <Numeric value={fact.value} format={factFormat(fact.value)} />
      {fact.unit ? <span className="ml-1 text-[10px] text-muted-foreground">{fact.unit}</span> : null}
    </span>
  );
}

/**
 * One concept: the row in force, then every earlier filing of the same period.
 *
 * The nesting is the argument. A restatement is not a separate kind of thing
 * with its own screen — it is *the same fact with a different filing date*, so
 * it is drawn as another line under the fact it restates, carrying the only
 * two fields that differ: when it was filed, and what it said.
 */
function ConceptRow({ history }: { history: ConceptHistory }) {
  const { concept, inForce, superseded } = history;
  const restatements = superseded.filter((row) => row.period_end === inForce.period_end);
  const older = superseded.filter((row) => row.period_end !== inForce.period_end);

  return (
    <li
      data-testid={`fact-${concept}`}
      className="border-b border-border px-3 py-2 last:border-b-0"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="font-mono text-xs">{conceptLabel(concept)}</span>
        <span className="flex items-baseline gap-4">
          <FactValue fact={inForce} />
          <span className="flex items-baseline gap-1.5">
            <span className={MICRO}>filed</span>
            <span className="font-mono text-[11px] tabular-nums">{inForce.filed_at}</span>
          </span>
          <span
            className="flex items-baseline gap-1.5"
            title="Days between the filing date and the as-of date: how old the newest knowable figure was."
          >
            <span className={MICRO}>stale</span>
            <Numeric value={inForce.days_stale} format="integer" className="text-[11px]" />
            <span className={MICRO}>d</span>
          </span>
        </span>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className={MICRO}>period</span>
        <Period fact={inForce} />
        {isForwardDated(inForce) ? (
          <StatusBadge
            tone="idle"
            testId={`forward-dated-${concept}`}
            title="Filed before the period it labels — an SEC tagging oddity on 0.012% of rows. Harmless under a rule that keys on the filing date, and shown rather than dropped."
          >
            Forward-dated
          </StatusBadge>
        ) : null}
      </div>

      {restatements.length > 0 ? (
        <div
          data-testid={`restatements-${concept}`}
          className="mt-2 border-l border-border pl-3"
        >
          <p className={MICRO}>
            Same period, filed <span className="tabular-nums">{restatements.length}</span> time
            {restatements.length === 1 ? '' : 's'} before
          </p>
          <ul className="mt-1 space-y-1">
            {restatements.map((row) => (
              <li
                key={`${row.filed_at}-${row.accession ?? ''}`}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[11px] text-muted-foreground"
              >
                <span className="font-mono tabular-nums">{row.filed_at}</span>
                <FactValue fact={row} />
                <StatusBadge
                  tone="idle"
                  title={
                    restatementKind(row, inForce) === 'refiled'
                      ? 'A later filing repeated this period unchanged — a comparative, not a correction. Most rows in the table are these.'
                      : 'A later filing changed this period’s figure. It applies from its own filing date forward and never backwards.'
                  }
                >
                  {restatementKind(row, inForce) === 'refiled' ? 'Refiled' : 'Restated'}
                </StatusBadge>
                {row.accession ? <span className="font-mono">{row.accession}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {older.length > 0 ? (
        <p className="mt-1 text-[11px] text-muted-foreground">
          <span className="tabular-nums">{older.length}</span> earlier period
          {older.length === 1 ? '' : 's'} also on file, superseded by this one.
        </p>
      ) : null}
    </li>
  );
}

/**
 * The point-in-time inspector: what did this strategy know, and when?
 *
 * The question a fundamental backtest always raises and usually cannot answer,
 * given a screen of its own (FUNDAMENTALS §6). Everything on it is anchored to
 * one as-of date: the server returns only rows filed on or before it, so what
 * is on screen is exactly the set of facts a run could legitimately have used
 * on that date — no more, and, importantly, no less.
 *
 * It is deliberately built from the served rows alone. The browser does not
 * recompute staleness, does not derive a ratio, and does not decide that a row
 * is too old to count; doing any of those would be a second implementation of
 * the rule this screen exists to make believable.
 */
export function FundamentalsInspector({
  instruments,
  symbol,
  asOf,
  onSymbolChange,
  onAsOfChange,
}: {
  instruments: Instrument[];
  symbol: string | null;
  asOf: string;
  onSymbolChange: (symbol: string) => void;
  onAsOfChange: (asOf: string) => void;
}) {
  const { facts, status, message, reload } = useInstrumentFacts(symbol, asOf);
  const histories = useMemo(() => groupByConcept(facts), [facts]);

  const filings = facts.length;

  return (
    <FillColumn className="gap-4 p-4">
      <Panel
        title="Point-in-time inspector"
        fill
        scroll
        actions={
          symbol ? (
            <StatusBadge tone="active" testId="inspector-subject">
              {symbol}
            </StatusBadge>
          ) : null
        }
        bodyClassName="space-y-4"
      >
        <Measure size="wide" className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,220px)]">
            <div className="space-y-1">
              <label className={MICRO} htmlFor="inspector-symbol">
                Instrument
              </label>
              <Select
                id="inspector-symbol"
                value={symbol ?? ''}
                onChange={(event) => onSymbolChange(event.target.value)}
              >
                <option value="">Choose an instrument…</option>
                {instruments.map((instrument) => (
                  <option key={instrument.symbol} value={instrument.symbol}>
                    {instrument.symbol} — {instrument.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <label className={MICRO} htmlFor="inspector-as-of">
                As of
              </label>
              <input
                id="inspector-as-of"
                type="date"
                className={fieldClasses}
                value={asOf}
                onChange={(event) => onAsOfChange(event.target.value)}
              />
            </div>
          </div>

          {/* The rule, stated where its consequences are on screen. Everything
              below is a demonstration of this sentence. */}
          <p className="border border-primary/40 bg-primary/5 p-3 text-xs leading-relaxed">
            Only facts filed on or before{' '}
            <span className="font-mono tabular-nums">{asOf}</span> are here. Timing comes from the
            filing date, never from the period: a restated figure applies from its own filing
            forward and never backwards, so a later filing of an older period is shown as another
            line under the fact it restates.
          </p>

          {symbol === null || symbol === '' ? (
            <EmptyState
              testId="inspector-no-symbol"
              icon={ScanSearch}
              title="Choose an instrument"
              detail="Pick a name and a date, and this shows every fact that had been filed by then — the value, the period it describes, when it was filed, and how stale it was."
            />
          ) : status === 'loading' ? (
            <EmptyState icon={Hourglass} title="Reading the filings…" role="status" />
          ) : status === 'unsupported' ? (
            <EmptyState
              testId="inspector-unsupported"
              icon={Database}
              title="No fundamentals on this backend"
              detail="This deployment does not serve filed fundamentals — the demo dataset has prices only. Point the app at the warehouse to inspect real filings."
            />
          ) : status === 'error' ? (
            <EmptyState
              testId="inspector-error"
              icon={ServerCrash}
              tone="error"
              title="Could not read the filings"
              detail={message ?? undefined}
              action={
                <Button type="button" size="sm" variant="outline" onClick={reload}>
                  Try again
                </Button>
              }
            />
          ) : histories.length === 0 ? (
            <EmptyState
              testId="inspector-empty"
              icon={FileClock}
              title="Nothing had been filed yet"
              detail={`No fact for ${symbol} had been filed on or before ${asOf}. That is an answer, not a failure: on that date a strategy reading fundamentals had nothing to read for this name, and its gate was shut.`}
            />
          ) : (
            <>
              <StatGrid testId="inspector-stats" min="12rem">
                <Stat label="Concepts known" title="Distinct concepts with at least one filing by the as-of date.">
                  <Numeric value={histories.length} format="integer" />
                </Stat>
                <Stat label="Filings visible" title="Rows filed on or before the as-of date. One fact can have many.">
                  <Numeric value={filings} format="integer" />
                </Stat>
                <Stat
                  label="Restated periods"
                  title="Concepts whose in-force period had already been filed more than once by this date."
                >
                  <Numeric
                    value={
                      histories.filter((history) =>
                        history.superseded.some(
                          (row) => row.period_end === history.inForce.period_end,
                        ),
                      ).length
                    }
                    format="integer"
                  />
                </Stat>
              </StatGrid>

              <ScrollRegion testId="inspector-facts" className="border border-border">
                <ul>
                  {histories.map((history) => (
                    <ConceptRow key={history.concept} history={history} />
                  ))}
                </ul>
              </ScrollRegion>

              <p className="text-[11px] text-muted-foreground">
                Filings dated after{' '}
                <span className="font-mono tabular-nums">{asOf}</span> are not shown, because on
                that date they did not exist. Move the date forward to watch a restatement arrive.
              </p>
            </>
          )}
        </Measure>
      </Panel>
    </FillColumn>
  );
}

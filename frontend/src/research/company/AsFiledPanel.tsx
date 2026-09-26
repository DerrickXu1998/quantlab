import { FileText } from 'lucide-react';
import { ScrollRegion } from '../../components/ui/layout';
import { StatusBadge } from '../../components/ui/status-badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { cn } from '../../lib/utils';
import { conceptLabel, formatCount, formatFactValue, formatStaleness } from '../format';
import { Panel, PanelEmpty, PanelState } from './Panel';
import type { AsFiledRow, ReadStatus } from './useCompany';

/**
 * The age past which a fundamental rule stops honouring a figure.
 *
 * `DEFAULT_MAX_STALE_DAYS` in `backend/src/quantlab/signals/fundamental.py`.
 * Mirrored here only to *mark* a row, never to filter one: the inspector's job
 * is to show what was on file, including the figure a rule would have ignored,
 * because "the accounts existed but were too old to trade on" is a different
 * answer from "there were no accounts".
 */
export const MAX_STALE_DAYS = 455;

/**
 * Why the table is empty, in the words that are actually true.
 *
 * Three different reasons, and the reader needs to know which one: nothing had
 * been filed *yet* on this date, nothing has *ever* been filed, or coverage was
 * unreadable so we do not know. Printing one sentence for all three is how a
 * gap in the warehouse gets read as a fact about the company.
 */
export function emptyDetail(symbol: string, asOf: string, hasAnyFilings: boolean | null): string {
  if (hasAnyFilings === null) {
    return `${symbol} has nothing on file as of ${asOf}. Coverage could not be read, so whether it has ever filed is unknown.`;
  }
  if (hasAnyFilings) {
    return `${symbol} has filings, but none had been published by ${asOf}. Move the as-of date forward.`;
  }
  return `${symbol} has never filed any of the concepts this warehouse maps. That is a hole in coverage, not a set of zeroes.`;
}

export interface AsFiledPanelProps {
  symbol: string;
  asOf: string;
  rows: AsFiledRow[];
  status: ReadStatus;
  message: string | null;
  /**
   * Whether this name has ever filed anything, from the coverage lists.
   *
   * `null` is "coverage could not be read", and it is not folded into `false`:
   * "this company has never filed" and "we could not find out" are different
   * sentences, and the empty state prints whichever is true.
   */
  hasAnyFilings: boolean | null;
  onRetry: () => void;
}

/**
 * The point-in-time inspector.
 *
 * Every figure carries the date it was filed, beside it, in the same row. That
 * is the whole discipline made visible: a reader can see that the revenue line
 * shown against a 2021 as-of date was filed in 2021 and not restated in 2023,
 * and can see how old it already was on the day it would have been traded on.
 */
export function AsFiledPanel({
  symbol,
  asOf,
  rows,
  status,
  message,
  hasAnyFilings,
  onRetry,
}: AsFiledPanelProps) {
  const inForce = rows.filter((row) => row.inForce);
  const superseded = rows.length - inForce.length;

  return (
    <Panel
      icon={FileText}
      title="As filed"
      purpose="The accounts as they were public on the as-of date. Each figure shows when it was filed and how old it already was."
      testId="company-as-filed"
      fill
      aside={
        status === 'ready' && rows.length > 0 ? (
          <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            {formatCount(inForce.length)} in force
            {superseded > 0 ? ` · ${formatCount(superseded)} superseded` : ''}
          </span>
        ) : null
      }
    >
      {status !== 'ready' ? (
        <PanelState
          status={status}
          message={message}
          subject="the accounts as filed"
          route="GET /instruments/{symbol}/fundamentals"
          onRetry={onRetry}
          testId="company-as-filed-state"
        />
      ) : rows.length === 0 ? (
        <PanelEmpty
          title="Nothing was on file on this date"
          detail={emptyDetail(symbol, asOf, hasAnyFilings)}
          testId="company-as-filed-empty"
        />
      ) : (
        <ScrollRegion testId="company-as-filed-rows">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Line item</TableHead>
                <TableHead className="text-right">As filed</TableHead>
                <TableHead>Filed at</TableHead>
                <TableHead>Period end</TableHead>
                <TableHead className="text-right">Age on {asOf}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={`${row.concept}-${row.filed_at}-${row.period_end}`}
                  className={cn(!row.inForce && 'opacity-60')}
                >
                  <TableCell className="text-xs">
                    <span className="flex items-center gap-2">
                      <span className="truncate">{conceptLabel(row.concept)}</span>
                      {row.inForce ? null : (
                        <StatusBadge tone="idle" title="A later filing supersedes this row.">
                          Superseded
                        </StatusBadge>
                      )}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono text-[11px] tabular-nums">
                    {formatFactValue(row.concept, row.value, row.unit)}
                  </TableCell>
                  <TableCell className="font-mono text-[11px] tabular-nums text-muted-foreground">
                    {row.filed_at}
                  </TableCell>
                  <TableCell className="font-mono text-[11px] tabular-nums text-muted-foreground">
                    {row.period_end}
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="flex items-center justify-end gap-2">
                      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                        {formatStaleness(row.days_stale)}
                      </span>
                      {row.days_stale > MAX_STALE_DAYS ? (
                        <StatusBadge
                          tone="idle"
                          title={`Older than ${MAX_STALE_DAYS} days — a fundamental rule would not have traded on this figure.`}
                        >
                          Stale
                        </StatusBadge>
                      ) : null}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            A figure older than {MAX_STALE_DAYS} days is marked stale: the fundamental rules stop
            honouring one past that age, so it is shown here but would not have been traded on.
          </p>
        </ScrollRegion>
      )}
    </Panel>
  );
}

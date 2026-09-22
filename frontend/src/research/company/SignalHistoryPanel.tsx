import { Activity } from 'lucide-react';
import { useMemo } from 'react';
import type { CompanySignalCount } from '../../api/types';
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
import { NOT_APPLICABLE, formatCount } from '../format';
import { Panel, PanelEmpty, PanelState } from './Panel';
import type { ReadStatus } from './useCompany';

export interface SignalHistoryPanelProps {
  symbol: string;
  signals: CompanySignalCount[];
  total: number;
  status: ReadStatus;
  message: string | null;
  onRetry: () => void;
}

/**
 * The firehose, scoped to one name.
 *
 * The old destination made 285,990 undifferentiated signal rows the entry point
 * to Research (docs/RESEARCH.md §1b). The same data, grouped by rule and bounded
 * to one company, is a fact *about that company* — which is what it was always
 * for. Ordered by how often each rule fired rather than by recency, because the
 * question here is "what does this name trip", not "what happened last".
 */
export function SignalHistoryPanel({
  symbol,
  signals,
  total,
  status,
  message,
  onRetry,
}: SignalHistoryPanelProps) {
  const ordered = useMemo(
    () =>
      [...signals].sort((a, b) =>
        b.count !== a.count ? b.count - a.count : a.rule_name < b.rule_name ? -1 : 1,
      ),
    [signals],
  );

  return (
    <Panel
      icon={Activity}
      title="Signal history"
      purpose="Which rules have ever fired on this name, how often, and when they last did."
      testId="company-signals"
      fill
      aside={
        status === 'ready' && ordered.length > 0 ? (
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            {formatCount(total)} signals
          </span>
        ) : null
      }
    >
      {status !== 'ready' ? (
        <PanelState
          status={status}
          message={message}
          subject="this name's signal history"
          route="GET /instruments/{symbol}/overview"
          onRetry={onRetry}
          testId="company-signals-state"
        />
      ) : ordered.length === 0 ? (
        <PanelEmpty
          title="No rule has fired on this name"
          detail={`Nothing has been materialised for ${symbol}. Only three of the twenty-two rules have ever been run over history, so silence here can mean "not yet run" as easily as "never triggered".`}
          testId="company-signals-empty"
        />
      ) : (
        <ScrollRegion testId="company-signals-rows">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rule</TableHead>
                <TableHead className="text-right">Fired</TableHead>
                <TableHead>Last fired</TableHead>
                <TableHead>Direction</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ordered.map((row) => (
                <TableRow key={row.rule_name}>
                  <TableCell className="truncate font-mono text-[11px]">{row.rule_name}</TableCell>
                  <TableCell className="text-right font-mono text-[11px] tabular-nums">
                    {formatCount(row.count)}
                  </TableCell>
                  <TableCell className="font-mono text-[11px] tabular-nums text-muted-foreground">
                    {row.last_date ?? NOT_APPLICABLE}
                  </TableCell>
                  <TableCell>
                    {row.last_direction ? (
                      /* Both directions are neutral, and deliberately so.
                         Red is reserved for losses. A bearish signal is a
                         direction a rule detected, not money lost — acted on
                         as a short it is how money is made — so colouring it
                         destructive would teach the reader that bearish means
                         a bad outcome, which is false. Colouring only bullish
                         with the accent implies the same thing more quietly.
                         The word carries the direction; the palette does not
                         editorialise about it. (The candlestick chart paints
                         down-candles destructive, which is a different claim:
                         a down bar is a realised decline, not a forecast.) */
                      <StatusBadge
                        tone="idle"
                        title={`The last signal from ${row.rule_name} was ${row.last_direction}.`}
                      >
                        {row.last_direction}
                      </StatusBadge>
                    ) : (
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {NOT_APPLICABLE}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
            Only rules with materialised history appear. A rule missing from this list has not
            necessarily passed over {symbol} without firing — it may never have been run.
          </p>
        </ScrollRegion>
      )}
    </Panel>
  );
}

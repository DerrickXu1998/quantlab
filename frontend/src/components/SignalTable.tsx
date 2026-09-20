import type { Signal } from '../api/client';
import { navigate } from '../chrome/router';
import { Button } from './ui/button';
import { Card, CardHeader, CardTitle } from './ui/card';
import { EmptyResults } from './ui/empty-state';
import { Numeric } from './ui/numeric';
import { StatusBadge, type StatusTone } from './ui/status-badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';

interface SignalTableProps {
  signals: Signal[];
  total: number;
  selectedId?: number | null;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onSelect: (signal: Signal) => void;
}

function formatTriggerValues(values: Record<string, unknown>): string {
  return Object.entries(values)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(', ');
}

// Red is reserved for losses and errors, so a bearish *signal* is not red —
// the accent marks the bullish side and the two read apart by fill, not hue.
const DIRECTION_TONE: Record<string, StatusTone> = {
  bullish: 'active',
  bearish: 'idle',
};

/**
 * The signal carries everything the run form needs: model name and version,
 * and the parameter values it fired with — handed to Strategies as `p_*`
 * params on the hash, so the prefill survives a refresh.
 */
export function rerunParams(signal: Signal): Record<string, string> {
  const params: Record<string, string> = {
    model: signal.rule_name,
    version: signal.rule_version,
  };
  for (const [key, value] of Object.entries(signal.parameters)) {
    params[`p_${key}`] = String(value);
  }
  return params;
}

export function SignalTable({
  signals,
  total,
  selectedId = null,
  page,
  pageSize,
  onPageChange,
  onSelect,
}: SignalTableProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <Card className="signal-table overflow-hidden">
      <CardHeader className="signal-table-header">
        <CardTitle>
          <span data-testid="signal-count">
            <Numeric value={total} format="integer" />
          </span>{' '}
          signal{total === 1 ? '' : 's'}
        </CardTitle>
      </CardHeader>

      {signals.length === 0 ? (
        <EmptyResults />
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Rule</TableHead>
                <TableHead>Direction</TableHead>
                <TableHead>Trigger values</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {signals.map((signal) => (
                <TableRow
                  key={signal.id}
                  className={
                    signal.id === selectedId
                      ? 'selected cursor-pointer bg-accent'
                      : 'cursor-pointer hover:bg-accent/50'
                  }
                  onClick={() => onSelect(signal)}
                >
                  <TableCell className="font-mono text-xs">{signal.symbol}</TableCell>
                  <TableCell className="font-mono text-xs tabular-nums">{signal.date}</TableCell>
                  <TableCell className="text-xs">
                    {signal.rule_name} v{signal.rule_version}
                  </TableCell>
                  <TableCell>
                    <StatusBadge
                      tone={DIRECTION_TONE[signal.direction] ?? 'idle'}
                      className={`badge badge-${signal.direction}`}
                    >
                      {signal.direction}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className="trigger-values font-mono text-xs text-muted-foreground">
                    {formatTriggerValues(signal.trigger_values)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      title={`Re-run ${signal.rule_name} with these parameters`}
                      onClick={(event) => {
                        // The row click selects the signal; the button navigates.
                        event.stopPropagation();
                        navigate('strategies', rerunParams(signal));
                      }}
                    >
                      Re-run
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <nav
            className="pagination flex items-center gap-4 border-t border-border px-3 py-2 text-xs"
            aria-label="Pagination"
          >
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page <= 0}
              onClick={() => onPageChange(page - 1)}
            >
              Previous
            </Button>
            <span className="text-muted-foreground">
              Page <Numeric value={page + 1} format="integer" /> of{' '}
              <Numeric value={pageCount} format="integer" />
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page >= pageCount - 1}
              onClick={() => onPageChange(page + 1)}
            >
              Next
            </Button>
          </nav>
        </>
      )}
    </Card>
  );
}

import type { Signal } from '../api/client';
import { EmptyResults } from './StatusStates';
import { Button } from './ui/button';
import { CardHeader, CardTitle } from './ui/card';
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

const DIRECTION_BADGE: Record<string, string> = {
  bullish: 'bg-success/15 text-success',
  bearish: 'bg-destructive/15 text-destructive',
};

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
    <section className="signal-table overflow-hidden rounded-lg border border-border bg-card text-card-foreground">
      <CardHeader className="signal-table-header border-b border-border">
        <CardTitle>
          <span data-testid="signal-count">{total}</span> signal{total === 1 ? '' : 's'}
        </CardTitle>
      </CardHeader>

      {signals.length === 0 ? (
        <div className="p-4">
          <EmptyResults />
        </div>
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
                  <TableCell className="font-medium">{signal.symbol}</TableCell>
                  <TableCell className="tabular-nums">{signal.date}</TableCell>
                  <TableCell>
                    {signal.rule_name} v{signal.rule_version}
                  </TableCell>
                  <TableCell>
                    <span
                      className={`badge badge-${signal.direction} inline-block rounded-full px-2 py-0.5 text-xs font-bold ${
                        DIRECTION_BADGE[signal.direction] ?? 'bg-muted text-muted-foreground'
                      }`}
                    >
                      {signal.direction}
                    </span>
                  </TableCell>
                  <TableCell className="trigger-values font-mono text-xs text-muted-foreground">
                    {formatTriggerValues(signal.trigger_values)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <nav
            className="pagination flex items-center gap-4 border-t border-border px-4 py-3 text-sm"
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
              Page {page + 1} of {pageCount}
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
    </section>
  );
}

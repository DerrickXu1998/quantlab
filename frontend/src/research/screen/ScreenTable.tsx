import { ArrowDown, ArrowUp } from 'lucide-react';
import type { ScreenMetric, ScreenResult } from '../../api/types';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { METRIC_FORMAT } from '../format';

/**
 * The ranked answer.
 *
 * Every figure goes through `METRIC_FORMAT`, which is what keeps
 * `close=17.68000030517578` off this surface (docs/RESEARCH.md §1e), and a
 * value the filings never supported renders as an em dash. Never a zero: a
 * missing book value does not make a company cheap.
 */
export function ScreenTable({
  result,
  metrics,
  onSelectSymbol,
  onSort,
  descending,
  busy,
}: {
  result: ScreenResult;
  metrics: ScreenMetric[];
  onSelectSymbol: (symbol: string) => void;
  /** Re-runs the screen ordered by this metric. A click, never a keystroke. */
  onSort: (metric: ScreenMetric) => void;
  /** The direction the answered query asked for, not one inferred from rows. */
  descending: boolean;
  busy: boolean;
}) {
  return (
    <Table data-testid="screen-table">
      <TableHeader>
        <TableRow className="sticky top-0 z-10 bg-card">
          <TableHead className="w-12 text-right">#</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead className="min-w-[10rem]">Name</TableHead>
          {metrics.map((metric) => {
            const { label, hint } = METRIC_FORMAT[metric];
            const sorted = result.sort_by === metric;
            return (
              <TableHead key={metric} className="text-right">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onSort(metric)}
                  title={`${hint} — click to rank by this`}
                  className={`inline-flex items-center gap-1 uppercase tracking-[0.12em] transition-colors hover:text-primary disabled:cursor-not-allowed disabled:opacity-40 ${
                    sorted ? 'text-primary' : ''
                  }`}
                >
                  {label}
                  {sorted ? <SortGlyph descending={descending} /> : null}
                </button>
              </TableHead>
            );
          })}
        </TableRow>
      </TableHeader>
      <TableBody>
        {result.rows.map((row, index) => (
          <TableRow
            key={row.symbol}
            data-testid={`screen-row-${row.symbol}`}
            onClick={() => onSelectSymbol(row.symbol)}
            className="cursor-pointer hover:bg-accent/40"
          >
            <TableCell className="text-right font-mono text-[11px] tabular-nums text-muted-foreground">
              {index + 1}
            </TableCell>
            <TableCell className="py-1">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectSymbol(row.symbol);
                }}
                className="font-mono text-[12px] text-foreground transition-colors hover:text-primary"
                title={`Open ${row.symbol} in Company`}
              >
                {row.symbol}
              </button>
            </TableCell>
            <TableCell className="max-w-[18rem] truncate text-xs text-muted-foreground">
              {row.name}
            </TableCell>
            {metrics.map((metric) => {
              const value = row.values[metric];
              const absent = value === null || value === undefined;
              return (
                <TableCell
                  key={metric}
                  className={`text-right font-mono text-[11px] tabular-nums ${
                    absent ? 'text-muted-foreground' : 'text-foreground'
                  }`}
                  title={absent ? 'Never filed for this name — not a zero.' : undefined}
                >
                  {METRIC_FORMAT[metric].render(value)}
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function SortGlyph({ descending }: { descending: boolean }) {
  const Icon = descending ? ArrowDown : ArrowUp;
  return (
    <Icon
      size={16}
      strokeWidth={1.5}
      aria-label={descending ? 'highest first' : 'lowest first'}
    />
  );
}

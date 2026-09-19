import type { Signal } from '../api/client';
import { EmptyResults } from './StatusStates';

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
    <section className="signal-table">
      <header className="signal-table-header">
        <h2>
          <span data-testid="signal-count">{total}</span> signal{total === 1 ? '' : 's'}
        </h2>
      </header>

      {signals.length === 0 ? (
        <EmptyResults />
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Date</th>
                <th>Rule</th>
                <th>Direction</th>
                <th>Trigger values</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((signal) => (
                <tr
                  key={signal.id}
                  className={signal.id === selectedId ? 'selected' : undefined}
                  onClick={() => onSelect(signal)}
                >
                  <td>{signal.symbol}</td>
                  <td>{signal.date}</td>
                  <td>
                    {signal.rule_name} v{signal.rule_version}
                  </td>
                  <td>
                    <span className={`badge badge-${signal.direction}`}>{signal.direction}</span>
                  </td>
                  <td className="trigger-values">{formatTriggerValues(signal.trigger_values)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <nav className="pagination" aria-label="Pagination">
            <button type="button" disabled={page <= 0} onClick={() => onPageChange(page - 1)}>
              Previous
            </button>
            <span>
              Page {page + 1} of {pageCount}
            </span>
            <button
              type="button"
              disabled={page >= pageCount - 1}
              onClick={() => onPageChange(page + 1)}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  );
}

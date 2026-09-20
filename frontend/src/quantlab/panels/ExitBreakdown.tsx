import type { ExecutionSummary, ExitReason, RunPerformanceV2 } from '../../api/types';
import { EXIT_REASON_LABELS } from '../../api/types';
import { Numeric } from '../chrome/Numeric';
import { Panel } from '../chrome/Panel';

const MICRO = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

/**
 * Why the run's positions closed, and what the closing cost.
 *
 * Not a chart: the useful question here is "did my stop do the work, or did
 * the signal?", and a count per reason answers it at a glance where a pie
 * chart would need decoding. Everything is read straight off the payload — the
 * browser tallies nothing (Constitution V).
 */
export function ExitBreakdown({
  performance,
  summary,
}: {
  performance: RunPerformanceV2;
  summary?: ExecutionSummary | null;
}) {
  const reasons = performance.exit_reasons ?? null;
  const costs = performance.costs ?? null;

  // A pre-change run carries neither, and inventing a breakdown out of the
  // trade list would be the frontend computing a figure it must not compute.
  if (!reasons && !costs && !summary) return null;

  const entries = Object.entries(reasons ?? {}).filter(
    (entry): entry is [ExitReason, number] => typeof entry[1] === 'number',
  );

  return (
    <div data-testid="exit-breakdown">
      <Panel title="How positions closed" bodyClassName="space-y-3">
        {entries.length > 0 ? (
          <table className="w-full" data-testid="exit-reasons">
            <caption className={`${MICRO} pb-1 text-left`}>Exits by reason</caption>
            <tbody>
              {entries.map(([reason, count]) => (
                <tr key={reason} className="border-t border-border">
                  <td className="py-1 text-[11px]">{EXIT_REASON_LABELS[reason] ?? reason}</td>
                  <td className="py-1 text-right">
                    <Numeric value={count} format="integer" className="text-[11px]" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            This run reported no exit-reason breakdown.
          </p>
        )}

        {costs ? (
          <dl
            data-testid="run-costs"
            className="flex flex-wrap gap-x-6 gap-y-1 border-t border-border pt-2 text-[11px]"
          >
            <div className="flex gap-2">
              <dt className={MICRO}>Commission</dt>
              <dd>
                <Numeric value={costs.commission} format="currency" className="text-[11px]" />
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className={MICRO}>Slippage</dt>
              <dd>
                <Numeric value={costs.slippage} format="currency" className="text-[11px]" />
              </dd>
            </div>
          </dl>
        ) : null}

        {summary ? <ExecutionSummaryStrip summary={summary} /> : null}
      </Panel>
    </div>
  );
}

/** One counter, rendered only when the engine reported it. */
function Counter({
  label,
  title,
  value,
  alarming,
}: {
  label: string;
  title: string;
  value: number | undefined;
  /** Non-zero here means the run did not test what the user thinks it tested. */
  alarming?: boolean;
}) {
  if (value === undefined) return null;
  const lit = alarming === true && value > 0;
  return (
    <div className="flex gap-2">
      <dt className={`${MICRO} ${lit ? 'text-destructive' : ''}`} title={title}>
        {label}
      </dt>
      <dd>
        <Numeric
          value={value}
          format="integer"
          tone={lit ? 'default' : 'muted'}
          className={`text-[11px] ${lit ? 'text-destructive' : ''}`}
        />
      </dd>
    </div>
  );
}

/**
 * What the engine did, and what it declined to do.
 *
 * The rejection counters matter as much as the fills. A strategy whose entries
 * were nearly all refused -- no free slot, still in cooldown, or bearish with
 * shorts switched off -- has not really been tested, and on the numbers alone
 * it is indistinguishable from one that signalled rarely. The ones that mean
 * "your signals were discarded" are lit in the loss colour when non-zero, so
 * the reader is not left to notice a 10 sitting quietly next to a 1.
 *
 * Counters the contract does not name are rendered only when present, so a
 * backend at the documented shape shows the four it does have and no blanks.
 */
function ExecutionSummaryStrip({ summary }: { summary: ExecutionSummary }) {
  return (
    <dl
      data-testid="execution-summary"
      className="flex flex-wrap gap-x-6 gap-y-1 border-t border-border pt-2 text-[11px]"
    >
      <Counter label="Orders" title="Entry and exit orders the strategy asked for." value={summary.orders} />
      <Counter label="Fills" title="Orders that actually traded." value={summary.fills} />
      <Counter
        label="No cash"
        title="Orders the book had no cash left to pay for."
        value={summary.rejected_no_cash}
        alarming
      />
      <Counter
        label="Slots full"
        title="Entries refused because max positions was already reached."
        value={summary.rejected_max_positions}
        alarming
      />
      <Counter
        label="In cooldown"
        title="Entries refused because that name had closed too recently."
        value={summary.rejected_cooldown}
        alarming
      />
      <Counter
        label="Shorts off"
        title="Bearish entries discarded because allow shorts is switched off. Turn it on, or read this as half the strategy never running."
        value={summary.rejected_shorts_disabled}
        alarming
      />
      <Counter
        label="Dropped"
        title="Signals on the last bar of the window, with no next bar to fill on."
        value={summary.dropped_no_bar}
        alarming
      />
      <Counter
        label="Contradictions"
        title="Bars where an entry and an exit fired for the same symbol at once."
        value={summary.contradictions}
      />
    </dl>
  );
}

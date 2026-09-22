import { ChevronRight } from 'lucide-react';

/**
 * What the run actually did, in the run's own words.
 *
 * This used to be a collapsed footnote reading "not a tradeable backtest",
 * because the list was a fixed tuple that said the same thing about every run
 * ever recorded — folding boilerplate away was the right call for boilerplate.
 *
 * It is not boilerplate any more. The lines are derived from the resolved
 * ExecutionConfig, so they state the commission that was charged, the fill
 * timing that was used and the stop that was in force: facts you need in order
 * to read the numbers beside them, and facts that differ from run to run.
 *
 * So it is never hidden — but it is not always *open*. Nine lines of prose in
 * the Overview hero pushed the equity curve into a band a third of its height,
 * which is the opposite of the density this surface is for. `defaultOpen`
 * lets the caller decide: closed in the hero, where the chart is the subject
 * and the count in the header is enough to say "there are nine of these";
 * open in the run detail, where reading them is the point. The summary row
 * carries the count either way, so the information is never silently absent.
 */
export function Assumptions({
  assumptions,
  defaultOpen = true,
}: {
  assumptions: string[];
  defaultOpen?: boolean;
}) {
  if (assumptions.length === 0) return null;

  return (
    <details
      data-testid="performance-assumptions"
      open={defaultOpen}
      className="group border border-border bg-card"
    >
      <summary
        aria-label="What this run assumed"
        className="flex cursor-pointer list-none items-center justify-between gap-3 border-b border-border px-3 py-2 marker:content-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [&::-webkit-details-marker]:hidden"
      >
        <span className="flex items-center gap-2">
          <ChevronRight
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="text-muted-foreground group-open:rotate-90"
          />
          <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            What this run assumed
          </span>
        </span>
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {assumptions.length}
        </span>
      </summary>
      <ul className="space-y-1 px-3 py-2 text-[11px] text-muted-foreground">
        {assumptions.map((line) => (
          <li key={line} className="flex gap-2">
            <span aria-hidden="true" className="text-primary">
              ·
            </span>
            {line}
          </li>
        ))}
      </ul>
      <p className="border-t border-border px-3 py-1.5 text-[10px] text-muted-foreground">
        Derived from the execution criteria this run was given, not written here — these figures are
        still a simulation and are not tradeable.
      </p>
    </details>
  );
}

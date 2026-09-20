/**
 * What the run actually did, in the run's own words.
 *
 * This used to be a collapsed footnote reading "not a tradeable backtest",
 * because the list was a fixed tuple that said the same thing about every run
 * ever recorded — folding boilerplate away was the right call for boilerplate.
 *
 * It is not boilerplate any more. §5 derives these lines from the resolved
 * ExecutionConfig, so they state the commission that was charged, the fill
 * timing that was used and the stop that was in force — facts you need in
 * order to read the numbers beside them, and facts that differ from run to
 * run. Real information does not go behind a disclosure triangle, so it is
 * open, above the trade log, and titled as what it is.
 */
export function Assumptions({ assumptions }: { assumptions: string[] }) {
  if (assumptions.length === 0) return null;

  return (
    <section
      data-testid="performance-assumptions"
      aria-label="What this run assumed"
      className="border border-border bg-card"
    >
      <header className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          What this run assumed
        </h2>
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {assumptions.length}
        </span>
      </header>
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
    </section>
  );
}

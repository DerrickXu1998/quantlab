/**
 * The caveats the backend shipped with the numbers.
 *
 * Rendered from the payload rather than written here, so the disclosure cannot
 * drift from what the computation actually did.
 */
export function Assumptions({ assumptions }: { assumptions: string[] }) {
  if (assumptions.length === 0) return null;

  return (
    <details data-testid="performance-assumptions" className="border-t border-border px-3 py-2">
      <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        Not a tradeable backtest — {assumptions.length} assumptions
      </summary>
      <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
        {assumptions.map((line) => (
          <li key={line} className="flex gap-2">
            <span aria-hidden="true" className="text-primary">
              ·
            </span>
            {line}
          </li>
        ))}
      </ul>
    </details>
  );
}

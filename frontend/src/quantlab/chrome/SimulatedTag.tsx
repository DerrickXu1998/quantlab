/**
 * Marks a panel whose numbers are not real.
 *
 * The backend computes signals and, from them, performance. It has no
 * execution, no order book and no live feed. Anything standing in for those is
 * invention, and has to say so on its face rather than in a footnote.
 */
export function SimulatedTag({ reason }: { reason: string }) {
  return (
    <span
      data-testid="simulated-tag"
      title={reason}
      className="rounded-sm border border-border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-muted-foreground"
    >
      Simulated
    </span>
  );
}

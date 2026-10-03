/**
 * A run against its benchmark, small enough for a table row.
 *
 * Both series arrive as growth of 1 from the same start (the backend scales
 * them; nothing is computed here but pixel positions), so where the lines end
 * relative to each other is the row's answer to "did it beat buy-and-hold".
 * Strategy in the accent, the benchmark dashed and muted, as on the full chart.
 */
export function Sparkline({
  strategy,
  benchmark,
  width = 112,
  height = 28,
  label,
}: {
  strategy: number[];
  benchmark: number[];
  width?: number;
  height?: number;
  label: string;
}) {
  const all = [...strategy, ...benchmark];
  if (strategy.length < 2 || all.length === 0) return null;
  const low = Math.min(...all);
  const high = Math.max(...all);
  const span = high - low || 1;
  const pad = 2;
  const path = (values: number[]) =>
    values
      .map((value, index) => {
        const x = pad + (index / Math.max(1, values.length - 1)) * (width - pad * 2);
        const y = pad + (1 - (value - low) / span) * (height - pad * 2);
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  const baseline = pad + (1 - (1 - low) / span) * (height - pad * 2);

  return (
    <svg
      role="img"
      aria-label={label}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="block"
      data-testid="run-sparkline"
    >
      {low <= 1 && high >= 1 ? (
        <line
          x1={pad}
          x2={width - pad}
          y1={baseline}
          y2={baseline}
          className="stroke-border stroke-1"
        />
      ) : null}
      {benchmark.length >= 2 ? (
        <path
          d={path(benchmark)}
          fill="none"
          className="stroke-muted-foreground stroke-1"
          strokeDasharray="2 2"
        />
      ) : null}
      <path d={path(strategy)} fill="none" className="stroke-primary" strokeWidth={1.5} />
    </svg>
  );
}

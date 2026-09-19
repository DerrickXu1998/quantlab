import type { PriceBar } from '../api/client';

interface PriceChartProps {
  bars: PriceBar[];
  markerDate?: string;
}

const WIDTH = 640;
const HEIGHT = 220;
const PADDING = 12;

export function PriceChart({ bars, markerDate }: PriceChartProps) {
  if (bars.length === 0) {
    return <p className="chart-empty">No price history available.</p>;
  }

  const closes = bars.map((bar) => bar.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;

  const xAt = (index: number) =>
    PADDING + (index / Math.max(1, bars.length - 1)) * (WIDTH - 2 * PADDING);
  const yAt = (close: number) => HEIGHT - PADDING - ((close - min) / span) * (HEIGHT - 2 * PADDING);

  const points = bars.map((bar, index) => `${xAt(index)},${yAt(bar.close)}`).join(' ');
  const markerIndex = markerDate ? bars.findIndex((bar) => bar.date === markerDate) : -1;

  return (
    <svg
      data-testid="price-chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="Close price history"
      className="price-chart"
    >
      <polyline points={points} fill="none" stroke="#4a7ebb" strokeWidth="1.5" />
      {markerIndex >= 0 && (
        <g data-testid="signal-marker">
          <line
            x1={xAt(markerIndex)}
            y1={PADDING}
            x2={xAt(markerIndex)}
            y2={HEIGHT - PADDING}
            stroke="#c0392b"
            strokeDasharray="4 3"
          />
          <circle cx={xAt(markerIndex)} cy={yAt(bars[markerIndex].close)} r="5" fill="#c0392b" />
        </g>
      )}
      <text x={PADDING} y={HEIGHT - 2} className="chart-axis-label">
        {bars[0].date}
      </text>
      <text x={WIDTH - PADDING} y={HEIGHT - 2} textAnchor="end" className="chart-axis-label">
        {bars[bars.length - 1].date}
      </text>
    </svg>
  );
}

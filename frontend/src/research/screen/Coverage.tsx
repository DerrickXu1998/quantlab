import type { ScreenMetric, ScreenMetricCoverage, ScreenResult } from '../../api/types';
import { StatGrid } from '../../components/ui/layout';
import { conceptLabel, formatCount, formatPercent, METRIC_FORMAT } from '../format';

/**
 * Coverage, per metric, on the screen that offers the metric.
 *
 * This is the single most important thing on this mode. Coverage is not
 * uniform — gross profit is filed by 237 instruments, revenue by 376, net
 * income by 468 (docs/RESEARCH.md §2) — so a gross-margin screen runs over
 * 237 names, not 598. Without this line the shortfall is invisible and the
 * result reads as "few companies qualified" when the truth is "most were
 * never measured". Those are opposite conclusions about the same table.
 */
export function CoverageLine({
  metric,
  coverage,
}: {
  metric: ScreenMetric;
  coverage: ScreenMetricCoverage | null;
}) {
  const { label } = METRIC_FORMAT[metric];

  if (!coverage) {
    return (
      <p data-testid={`coverage-${metric}`} className="text-[11px] text-muted-foreground">
        {label} — coverage is reported once the screen runs.
      </p>
    );
  }

  const share = coverage.universe > 0 ? coverage.measured / coverage.universe : 0;
  const requires = coverage.requires ?? [];

  return (
    <div data-testid={`coverage-${metric}`} className="space-y-1">
      <p className="font-mono text-[10px] tabular-nums tracking-[0.04em] text-muted-foreground">
        {label} — {formatCount(coverage.measured)} of {formatCount(coverage.universe)}{' '}
        names measured
        <span className="ml-1.5 text-foreground">({formatPercent(share, 0)})</span>
      </p>
      {/* A hairline, not a chart: the ratio at a glance, in the one accent. */}
      <div
        className="h-px w-full bg-border"
        role="presentation"
        title={`${coverage.measured} of ${coverage.universe} measured`}
      >
        <div
          className="h-px bg-primary"
          style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }}
        />
      </div>
      {requires.length > 0 ? (
        <p className="text-[11px] text-muted-foreground">
          needs {requires.map(conceptLabel).join(', ').toLowerCase()}
        </p>
      ) : null}
    </div>
  );
}

function Figure({
  label,
  value,
  detail,
  tone,
  testId,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: 'accent';
  testId: string;
}) {
  return (
    <div data-testid={testId}>
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <p
        className={`mt-0.5 font-mono text-lg tabular-nums ${
          tone === 'accent' ? 'text-primary' : 'text-foreground'
        }`}
      >
        {value}
      </p>
      <p className="mt-0.5 max-w-[16rem] text-[11px] leading-snug text-muted-foreground">{detail}</p>
    </div>
  );
}

/**
 * Where the universe went: the two exclusions, never added together.
 *
 * `excluded_by_constraint` is a finding — those names were measured and did
 * not qualify. `excluded_unmeasured` is a gap in the filings — nobody ever
 * measured them, and they are neither pass nor fail. A single "excluded"
 * number would let a reader draw a conclusion about companies from a fact
 * about the warehouse.
 */
export function ExclusionLedger({ result }: { result: ScreenResult }) {
  return (
    <StatGrid testId="screen-exclusions" min="10rem" className="gap-y-5">
      <Figure
        testId="exclusion-shown"
        label="Shown"
        value={formatCount(result.rows.length)}
        detail="Names that met every constraint, ranked."
        tone="accent"
      />
      <Figure
        testId="exclusion-constraint"
        label="Did not qualify"
        value={formatCount(result.excluded_by_constraint)}
        detail="Measured, and failed at least one constraint. This is a finding."
      />
      <Figure
        testId="exclusion-unmeasured"
        label="Never measured"
        value={formatCount(result.excluded_unmeasured)}
        detail="Dropped because a constrained ratio could not be computed from what has been filed. Not a pass and not a fail."
      />
      <Figure
        testId="exclusion-universe"
        label="Universe"
        value={formatCount(result.universe_size)}
        detail={`Members of ${result.universe}.`}
      />
    </StatGrid>
  );
}

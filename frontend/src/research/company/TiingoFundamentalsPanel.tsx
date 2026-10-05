import { ExternalLink, FileSpreadsheet } from 'lucide-react';
import { useMemo, useState } from 'react';
import type {
  CompanyFundamentals,
  DailyFundamentals,
  DailyMetric,
  StatementLine,
  StatementType,
} from '../../api/types';
import { StatusBadge } from '../../components/ui/status-badge';
import { TabBar, tabId } from '../../components/ui/tabs';
import {
  METRIC_FORMAT,
  NOT_APPLICABLE,
  formatStatementValue,
} from '../format';
import { Panel, PanelState } from './Panel';
import type { ReadStatus } from './useCompany';

/** The release counts a reader can ask for; the server caps it at 40. */
export const RELEASE_CHOICES = [4, 8, 12, 20, 40] as const;

const DAILY_METRICS: DailyMetric[] = [
  'market_cap',
  'enterprise_value',
  'pe_ratio',
  'pb_ratio',
  'peg_ratio_1y',
];

const STATEMENTS: { id: StatementType; label: string }[] = [
  { id: 'incomeStatement', label: 'Income' },
  { id: 'balanceSheet', label: 'Balance sheet' },
  { id: 'cashFlow', label: 'Cash flow' },
  { id: 'overview', label: 'Ratios' },
];

/**
 * Tiingo's fundamentals for the company, as they stood on the as-of date.
 *
 * Three questions, in the order a reader asks them: who Tiingo says this is,
 * what the market has valued it at day by day, and what each quarterly and
 * annual release reported. Everything is cut at the as-of date — a release
 * filed the day after is not on screen — so this panel agrees with a backtest
 * standing on the same date.
 *
 * Statement figures are shown as Tiingo published them, by Tiingo's own field
 * names, with its definition on hover. They are not the filed concepts the
 * panel above resolves, and are labelled as Tiingo's so the two are never
 * mistaken for one another.
 */
export function TiingoFundamentalsPanel({
  symbol,
  data,
  status,
  message,
  releases,
  onReleases,
  onRetry,
}: {
  symbol: string;
  data: CompanyFundamentals | null;
  status: ReadStatus;
  message: string | null;
  releases: number;
  onReleases: (releases: number) => void;
  onRetry: () => void;
}) {
  const empty =
    data !== null && !data.profile && data.daily.length === 0 && data.lines.length === 0;

  return (
    <Panel
      icon={FileSpreadsheet}
      title="Tiingo fundamentals"
      purpose="What Tiingo published about this company up to the as-of date: its profile, the daily valuation, and every release's statements line by line. Hover a field for Tiingo's definition."
      testId="tiingo-fundamentals"
      aside={
        status === 'ready' && data?.releases.length ? (
          <label className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
            Releases
            <select
              aria-label="How many releases"
              className="h-7 border border-input bg-background px-1 text-xs"
              value={releases}
              onChange={(event) => onReleases(Number(event.target.value))}
            >
              {RELEASE_CHOICES.map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </label>
        ) : null
      }
    >
      {status !== 'ready' ? (
        <PanelState
          status={status}
          message={message}
          subject="Tiingo's fundamentals"
          route={`/instruments/${symbol}/fundamentals/tiingo`}
          onRetry={onRetry}
          testId="tiingo-fundamentals-state"
        />
      ) : data === null || empty ? (
        <p data-testid="tiingo-fundamentals-empty" className="p-3 text-xs text-muted-foreground">
          Tiingo has published nothing for {symbol} on or before this date. That is a gap in
          coverage (Tiingo covers US equities and ADRs), not a finding about the company.
        </p>
      ) : (
        <div className="flex flex-col gap-4 p-3">
          {data.profile ? <Profile profile={data.profile} /> : null}
          {data.daily.length > 0 ? <Valuation daily={data.daily} /> : null}
          {data.lines.length > 0 ? <Statements data={data} /> : null}
        </div>
      )}
    </Panel>
  );
}

function Profile({ profile }: { profile: NonNullable<CompanyFundamentals['profile']> }) {
  const currency = profile.reporting_currency?.toUpperCase() ?? null;
  const converted = currency !== null && currency !== 'USD';
  const items: [string, string | null][] = [
    ['Tiingo sector', profile.sector ?? null],
    ['Tiingo industry', profile.industry ?? null],
    ['SIC', profile.sic_code ? `${profile.sic_code} · ${profile.sic_industry ?? ''}`.trim() : null],
    ['Location', profile.location ?? null],
    ['Reports in', currency],
    ['permaTicker', profile.perma_ticker ?? null],
  ];
  return (
    <section data-testid="tiingo-profile" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {profile.is_active === false ? <StatusBadge tone="bad">Delisted</StatusBadge> : null}
        {profile.is_adr ? <StatusBadge tone="idle">ADR</StatusBadge> : null}
        {converted ? (
          <StatusBadge
            tone="idle"
            title={`Files in ${currency}; Tiingo converts every figure to USD at the rate of the day.`}
          >
            Converted from {currency}
          </StatusBadge>
        ) : null}
        {profile.company_website ? (
          <ProfileLink href={profile.company_website} label="Website" />
        ) : null}
        {profile.sec_filing_website ? (
          <ProfileLink href={profile.sec_filing_website} label="SEC filings" />
        ) : null}
      </div>
      <dl className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-x-4 gap-y-2">
        {items.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              {label}
            </dt>
            <dd className="mt-0.5 truncate text-sm" title={value ?? undefined}>
              {value || NOT_APPLICABLE}
            </dd>
          </div>
        ))}
      </dl>
      <p className="font-mono text-[11px] text-muted-foreground">
        Statements updated by Tiingo {shortDate(profile.statement_last_updated)} · daily{' '}
        {shortDate(profile.daily_last_updated)} · profile read {profile.fetched_at ?? NOT_APPLICABLE}
      </p>
    </section>
  );
}

function ProfileLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 text-xs text-primary underline-offset-2 hover:underline"
    >
      {label}
      <ExternalLink size={12} strokeWidth={1.5} aria-hidden="true" />
    </a>
  );
}

function shortDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : NOT_APPLICABLE;
}

/**
 * The daily valuation, one metric at a time.
 *
 * One line, to scale, between its own minimum and maximum, with both and the
 * dates at the ends written on the chart — enough to read a re-rating, not a
 * charting package.
 */
function Valuation({ daily }: { daily: DailyFundamentals[] }) {
  const [metric, setMetric] = useState<DailyMetric>('pe_ratio');
  const points = useMemo(
    () =>
      daily
        .map((day) => ({ date: day.date, value: day[metric] }))
        .filter((point): point is { date: string; value: number } =>
          typeof point.value === 'number' && Number.isFinite(point.value),
        ),
    [daily, metric],
  );
  const { label, render } = METRIC_FORMAT[metric];
  const latest = points.length > 0 ? points[points.length - 1] : null;

  return (
    <section data-testid="tiingo-valuation" className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Daily metric">
        {DAILY_METRICS.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={item === metric}
            onClick={() => setMetric(item)}
            className={`border px-2 py-0.5 font-mono text-[11px] transition-colors ${
              item === metric
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:text-foreground'
            }`}
          >
            {METRIC_FORMAT[item].label}
          </button>
        ))}
      </div>
      <p className="font-mono text-sm tabular-nums" data-testid="tiingo-valuation-latest">
        {label} {latest ? render(latest.value) : NOT_APPLICABLE}
        {latest ? <span className="ml-2 text-xs text-muted-foreground">on {latest.date}</span> : null}
      </p>
      {points.length >= 2 ? (
        <LineChart points={points} render={render} label={label} />
      ) : (
        <p className="text-xs text-muted-foreground">
          Tiingo published fewer than two days of {label} up to this date.
        </p>
      )}
    </section>
  );
}

const CHART = { width: 640, height: 160, left: 64, right: 8, top: 10, bottom: 22 };

function LineChart({
  points,
  render,
  label,
}: {
  points: { date: string; value: number }[];
  render: (value: number) => string;
  label: string;
}) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;
  const innerWidth = CHART.width - CHART.left - CHART.right;
  const innerHeight = CHART.height - CHART.top - CHART.bottom;
  const x = (index: number) => CHART.left + (index / (points.length - 1)) * innerWidth;
  const y = (value: number) => CHART.top + (1 - (value - min) / span) * innerHeight;
  const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(' ');

  return (
    <svg
      viewBox={`0 0 ${CHART.width} ${CHART.height}`}
      // Left-aligned at its natural width: centred in a wide panel, a fixed
      // aspect ratio letterboxes the line away from its labels.
      preserveAspectRatio="xMinYMid meet"
      className="h-40 w-full max-w-[40rem]"
      role="img"
      aria-label={`${label} from ${points[0].date} to ${points[points.length - 1].date}, between ${render(min)} and ${render(max)}`}
      data-testid="tiingo-valuation-chart"
    >
      <line
        x1={CHART.left}
        x2={CHART.width - CHART.right}
        y1={y(max)}
        y2={y(max)}
        className="stroke-border"
        strokeDasharray="2 3"
      />
      <line
        x1={CHART.left}
        x2={CHART.width - CHART.right}
        y1={y(min)}
        y2={y(min)}
        className="stroke-border"
        strokeDasharray="2 3"
      />
      <text x={CHART.left - 6} y={y(max) + 4} textAnchor="end" className="fill-muted-foreground font-mono text-[10px]">
        {render(max)}
      </text>
      <text x={CHART.left - 6} y={y(min) + 4} textAnchor="end" className="fill-muted-foreground font-mono text-[10px]">
        {render(min)}
      </text>
      <path d={path} fill="none" className="stroke-primary" strokeWidth={1.25} />
      <text x={CHART.left} y={CHART.height - 6} className="fill-muted-foreground font-mono text-[10px]">
        {points[0].date}
      </text>
      <text
        x={CHART.width - CHART.right}
        y={CHART.height - 6}
        textAnchor="end"
        className="fill-muted-foreground font-mono text-[10px]"
      >
        {points[points.length - 1].date}
      </text>
    </svg>
  );
}

/**
 * Every field of every release, as a grid: one statement at a time, filterable
 * by name or Tiingo code. Releases are columns, newest on the left, each headed
 * by its fiscal period and the date it was posted to the SEC.
 */
function Statements({ data }: { data: CompanyFundamentals }) {
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const line of data.lines) map.set(line.statement, (map.get(line.statement) ?? 0) + 1);
    return map;
  }, [data.lines]);
  const firstWithLines = STATEMENTS.find((item) => (counts.get(item.id) ?? 0) > 0)?.id ?? 'incomeStatement';
  const [statement, setStatement] = useState<StatementType>(firstWithLines);
  const [filter, setFilter] = useState('');

  const needle = filter.trim().toLowerCase();
  const lines: StatementLine[] = data.lines.filter(
    (line) =>
      line.statement === statement &&
      (needle === '' ||
        line.label.toLowerCase().includes(needle) ||
        line.code.toLowerCase().includes(needle)),
  );

  return (
    <section data-testid="tiingo-statements" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TabBar
          label="Statement"
          idPrefix="tiingo-statement"
          value={statement}
          onChange={setStatement}
          items={STATEMENTS.map((item) => ({
            id: item.id,
            label: item.label,
            badge: counts.get(item.id) ?? 0,
            badgeLabel: `${counts.get(item.id) ?? 0} fields`,
          }))}
        />
        <input
          type="search"
          aria-label="Filter fields"
          placeholder="Filter fields, e.g. debt or ncfo"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          className="h-8 w-56 max-w-full border border-input bg-background px-2 text-xs"
        />
      </div>
      <div
        role="tabpanel"
        id={`tiingo-statement-panel-${statement}`}
        aria-labelledby={tabId('tiingo-statement', statement)}
        className="overflow-x-auto"
      >
        <table className="w-full border-collapse text-xs" data-testid="tiingo-statement-table">
          <thead>
            <tr className="border-b border-border">
              <th className="sticky left-0 z-10 min-w-[12rem] bg-card py-1.5 pr-3 text-left font-mono text-[11px] font-normal uppercase tracking-[0.12em] text-muted-foreground">
                Field
              </th>
              {data.releases.map((release) => (
                <th
                  key={`${release.filed_at}-${release.label}`}
                  className="whitespace-nowrap px-2 py-1.5 text-right font-normal"
                  title={`Posted to the SEC ${release.filed_at}`}
                >
                  <span className="block font-mono text-[11px] text-foreground">{release.label}</span>
                  <span className="block font-mono text-[10px] text-muted-foreground">{release.filed_at}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 ? (
              <tr>
                <td colSpan={data.releases.length + 1} className="py-3 text-muted-foreground">
                  No field matches “{filter}”.
                </td>
              </tr>
            ) : (
              lines.map((line) => (
                <tr key={line.code} className="border-b border-border/60 hover:bg-muted/30">
                  <th
                    scope="row"
                    className="sticky left-0 z-10 bg-card py-1 pr-3 text-left font-normal"
                    title={line.description ? `${line.description} (${line.code})` : line.code}
                  >
                    <span className="text-foreground">{line.label}</span>
                    <span className="ml-1.5 font-mono text-[10px] text-muted-foreground">{line.code}</span>
                  </th>
                  {line.values.map((value, index) => (
                    <td
                      key={index}
                      className={`whitespace-nowrap px-2 py-1 text-right font-mono tabular-nums ${
                        value !== null && value < 0 ? 'text-destructive' : ''
                      }`}
                    >
                      {formatStatementValue(value, line.units)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default TiingoFundamentalsPanel;

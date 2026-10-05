/**
 * Number formatting for the research destination.
 *
 * This file exists because of one screenshot: the signal table rendered
 * `close=17.68000030517578, prior_min_low=17.829999923706055`. Those are
 * float64s printed with full precision, and no human writes a price to
 * seventeen significant figures. A table that does reads as debug output, and
 * that colours every judgement made about the numbers next to it
 * (docs/RESEARCH.md §1e).
 *
 * Everything here renders into a `tabular-nums` context, so widths are
 * consistent and digits line up down a column. None of it converts: a figure
 * filed in USD is shown in USD, scaled for reading but never re-based.
 */

/** Renders as an em dash, which is the house form for "not applicable". */
export const NOT_APPLICABLE = '—';

/**
 * The distinction the whole destination turns on.
 *
 * `null` is *unknown* — not filed, not measured, outside coverage — and it is
 * never a zero. A missing book value does not make a company cheap; a missing
 * margin does not make it unprofitable. Anywhere a number could be absent,
 * absence renders as an em dash and never as `0`, so a reader cannot mistake
 * a hole in the data for a finding.
 */
function absent(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined || !Number.isFinite(value);
}

/**
 * A price or any figure read at human scale.
 *
 * Two decimals below 1,000 and none above: the cents matter on a $17.68 close
 * and are noise on a $67,060,000,000 revenue line, which `compact` handles.
 */
export function formatPrice(value: number | null | undefined, currency?: string): string {
  if (absent(value)) return NOT_APPLICABLE;
  const digits = Math.abs(value) >= 1000 ? 0 : 2;
  const text = value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return currency ? `${text} ${currency}` : text;
}

const SCALES: readonly [number, string][] = [
  [1e12, 'T'],
  [1e9, 'bn'],
  [1e6, 'm'],
  [1e3, 'k'],
];

/**
 * Accounting magnitudes, scaled to three significant figures.
 *
 * Caterpillar's FY2023 revenue is 67060000000. Read as digits it is a counting
 * exercise; read as `67.1bn` it is a fact. The suffix is carried rather than
 * the reader tracking zeroes.
 */
export function formatCompact(value: number | null | undefined): string {
  if (absent(value)) return NOT_APPLICABLE;
  const sign = value < 0 ? '-' : '';
  const magnitude = Math.abs(value);
  for (const [scale, suffix] of SCALES) {
    if (magnitude >= scale) {
      const scaled = magnitude / scale;
      // Three significant figures: 67.1bn, 6.71bn, 671m all read the same way.
      const digits = scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2;
      return `${sign}${scaled.toFixed(digits)}${suffix}`;
    }
  }
  return `${sign}${magnitude.toFixed(magnitude < 1 ? 2 : 0)}`;
}

/** A multiple, as in a P/E of 11.6×. The glyph is part of the unit. */
export function formatMultiple(value: number | null | undefined): string {
  if (absent(value)) return NOT_APPLICABLE;
  return `${value.toFixed(1)}×`;
}

/**
 * A ratio held as a fraction, shown as a percentage.
 *
 * One decimal: an ROE is meaningful to a tenth of a point and spuriously
 * precise beyond it, given it is built from figures that get restated.
 */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (absent(value)) return NOT_APPLICABLE;
  return `${(value * 100).toFixed(digits)}%`;
}

/** A plain count, grouped. */
export function formatCount(value: number | null | undefined): string {
  if (absent(value)) return NOT_APPLICABLE;
  return value.toLocaleString('en-US');
}

/**
 * How a screen metric is written.
 *
 * Kept beside the formatters rather than in the screen UI so that a metric
 * added to the contract cannot acquire two different renderings in two panels.
 */
/** A ratio that is not a multiple: a current ratio of 1.07, a PEG of 1.30. */
function formatRatio(v: number | null | undefined): string {
  return absent(v) ? NOT_APPLICABLE : v.toFixed(2);
}

/** A whole-number score, such as the 0–9 Piotroski F-score. */
function formatScore(v: number | null | undefined): string {
  return absent(v) ? NOT_APPLICABLE : String(Math.round(v));
}

/** A dollar magnitude, scaled: $4.90T, $67.1bn. */
function formatDollars(v: number | null | undefined): string {
  return absent(v) ? NOT_APPLICABLE : `$${formatCompact(v)}`.replace('$-', '-$');
}

/** Where a screen metric comes from: computed here, or as Tiingo publishes it. */
export type MetricSource = 'filed' | 'tiingo';

export const METRIC_FORMAT = {
  pe: { label: 'P/E', render: formatMultiple, hint: 'Price ÷ earnings' },
  pb: { label: 'P/B', render: formatMultiple, hint: 'Price ÷ book value' },
  roe: { label: 'ROE', render: formatPercent, hint: 'Net income ÷ equity' },
  leverage: {
    label: 'Leverage',
    render: (v: number | null | undefined) => (absent(v) ? NOT_APPLICABLE : v.toFixed(2)),
    hint: 'Total liabilities ÷ total assets',
  },
  net_margin: { label: 'Net margin', render: formatPercent, hint: 'Net income ÷ revenue' },
  gross_margin: { label: 'Gross margin', render: formatPercent, hint: 'Gross profit ÷ revenue' },
  current_ratio: {
    label: 'Current ratio',
    render: (v: number | null | undefined) => (absent(v) ? NOT_APPLICABLE : v.toFixed(2)),
    hint: 'Current assets ÷ current liabilities',
  },
  // Published by Tiingo. Labels say so, because a P/E computed here and the
  // one Tiingo publishes are two numbers, and a ranking must say which it used.
  market_cap: { label: 'Market cap', render: formatDollars, hint: 'Tiingo daily: shares × price' },
  enterprise_value: {
    label: 'Enterprise value',
    render: formatDollars,
    hint: 'Tiingo daily: market cap + debt − cash',
  },
  pe_ratio: { label: 'P/E (Tiingo)', render: formatMultiple, hint: 'Tiingo daily price ÷ earnings; a loss-maker has none' },
  pb_ratio: { label: 'P/B (Tiingo)', render: formatMultiple, hint: 'Tiingo daily price ÷ book value; none on negative book' },
  peg_ratio_1y: {
    label: 'PEG 1y',
    render: formatRatio,
    hint: 'Tiingo daily: P/E ÷ trailing 1-year EPS growth; none when negative',
  },
  roe_reported: { label: 'ROE (Tiingo)', render: formatPercent, hint: 'Tiingo quarterly: net income ÷ equity' },
  roa_reported: { label: 'ROA (Tiingo)', render: formatPercent, hint: 'Tiingo quarterly: net income ÷ total assets' },
  gross_margin_reported: {
    label: 'Gross margin (Tiingo)',
    render: formatPercent,
    hint: 'Tiingo quarterly: (revenue − cost of revenue) ÷ revenue',
  },
  current_ratio_reported: {
    label: 'Current ratio (Tiingo)',
    render: formatRatio,
    hint: 'Tiingo quarterly: current assets ÷ current liabilities',
  },
  debt_equity_reported: {
    label: 'Debt/equity (Tiingo)',
    render: formatRatio,
    hint: 'Tiingo quarterly: total debt ÷ equity; none on negative equity',
  },
  revenue_qoq: { label: 'Revenue QoQ', render: formatPercent, hint: 'Tiingo quarterly: revenue growth on the prior quarter' },
  eps_qoq: { label: 'EPS QoQ', render: formatPercent, hint: 'Tiingo quarterly: EPS growth on the prior quarter' },
  piotroski_f_score: {
    label: 'Piotroski F',
    render: formatScore,
    hint: 'Tiingo quarterly: 0–9 score of financial strength',
  },
} as const;

/** Which metrics Tiingo publishes, in the order the screen offers them. */
export const TIINGO_METRICS = [
  'market_cap',
  'enterprise_value',
  'pe_ratio',
  'pb_ratio',
  'peg_ratio_1y',
  'roe_reported',
  'roa_reported',
  'gross_margin_reported',
  'current_ratio_reported',
  'debt_equity_reported',
  'revenue_qoq',
  'eps_qoq',
  'piotroski_f_score',
] as const;

export function metricSource(metric: string): MetricSource {
  return (TIINGO_METRICS as readonly string[]).includes(metric) ? 'tiingo' : 'filed';
}

/**
 * What a coverage line says a metric needs. `tiingo:peRatio` is a published
 * field, not a filed concept, and is named as one.
 */
export function requirementLabel(requirement: string): string {
  if (requirement.startsWith('tiingo:')) return `Tiingo's ${requirement.slice(7)}`;
  return conceptLabel(requirement).toLowerCase();
}

/**
 * One statement figure, in the unit Tiingo declares for it.
 *
 * `%` fields are held as fractions (0.4718 is 47.2%); `$` fields are scaled;
 * blank-unit fields are counts (shares) or ratios, told apart by magnitude.
 */
export function formatStatementValue(value: number | null | undefined, units?: string): string {
  if (absent(value)) return NOT_APPLICABLE;
  if (units === '%') return formatPercent(value);
  if (units === '$') {
    // Per-share figures (EPS, book value per share) are small; keep the cents.
    return Math.abs(value) < 1000 ? `$${value.toFixed(2)}`.replace('$-', '-$') : formatDollars(value);
  }
  return Math.abs(value) >= 1e4 ? formatCompact(value) : formatRatio(value);
}

/**
 * A filed concept's name, written the way an analyst says it.
 *
 * `operating_cash_flow` is a column name; "Operating cash flow" is the line
 * item. The fallback un-snakes anything unmapped rather than hiding it, since
 * a concept the UI does not recognise is still a real filed figure.
 */
const CONCEPT_LABELS: Record<string, string> = {
  revenue: 'Revenue',
  gross_profit: 'Gross profit',
  operating_income: 'Operating income',
  net_income: 'Net income',
  equity: 'Shareholders’ equity',
  total_assets: 'Total assets',
  total_liabilities: 'Total liabilities',
  current_assets: 'Current assets',
  current_liabilities: 'Current liabilities',
  cash: 'Cash',
  long_term_debt: 'Long-term debt',
  capex: 'Capital expenditure',
  operating_cash_flow: 'Operating cash flow',
  shares_outstanding: 'Shares outstanding',
  short_volume: 'Short volume',
  short_exempt_volume: 'Short exempt volume',
  total_volume: 'Total volume',
  net_short_position: 'Net short position',
};

export function conceptLabel(concept: string): string {
  const known = CONCEPT_LABELS[concept];
  if (known) return known;
  return concept.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

/**
 * Concepts counted in shares rather than currency.
 *
 * Share counts are magnitudes like revenue but carry no currency, and showing
 * `USD` beside a share count is simply wrong.
 */
const SHARE_CONCEPTS = new Set(['shares_outstanding', 'short_volume', 'short_exempt_volume', 'total_volume']);

export function formatFactValue(concept: string, value: number, unit?: string | null): string {
  const scaled = formatCompact(value);
  if (SHARE_CONCEPTS.has(concept)) return `${scaled} sh`;
  const currency = unit && unit.toUpperCase() !== 'PURE' ? unit.toUpperCase() : '';
  return currency ? `${scaled} ${currency}` : scaled;
}

/**
 * One entry from a signal's `trigger_values`.
 *
 * The raw object is `{close: 17.68000030517578, prior_min_low: 17.8299999}`.
 * The key is a snake-cased identifier and the value a full-precision float;
 * both need work before a person reads them, and doing it here means the
 * signal table and the company page cannot render the same trigger two ways.
 */
export interface FormattedTrigger {
  label: string;
  value: string;
}

export function formatTriggers(
  triggers: Record<string, unknown> | null | undefined,
): FormattedTrigger[] {
  if (!triggers) return [];
  return Object.entries(triggers).map(([key, raw]) => {
    // Rule-qualified keys arrive as `pe-filter.pe_ratio`; the rule is already
    // named in the row, so only the measure is worth the column width.
    const measure = key.includes('.') ? key.slice(key.lastIndexOf('.') + 1) : key;
    const label = measure.replace(/_/g, ' ');
    if (typeof raw !== 'number' || !Number.isFinite(raw)) {
      return { label, value: raw === null || raw === undefined ? NOT_APPLICABLE : String(raw) };
    }
    // Ratios, oscillators and prices all land here. Magnitude is the only
    // signal available about which it is, and it is enough to stop the
    // seventeen-digit dump without pretending to know the unit.
    const magnitude = Math.abs(raw);
    if (magnitude >= 1e6) return { label, value: formatCompact(raw) };
    if (magnitude >= 100) return { label, value: raw.toFixed(1) };
    return { label, value: raw.toFixed(2) };
  });
}

/**
 * How long ago a figure was filed, in the units a reader thinks in.
 *
 * Staleness is the fact that decides whether a fundamental figure should be
 * trusted at all — the rules stop honouring one past 455 days — so it is
 * rendered as a duration rather than a date difference the reader computes.
 */
export function formatStaleness(days: number | null | undefined): string {
  if (absent(days)) return NOT_APPLICABLE;
  const whole = Math.round(days);
  if (whole < 1) return 'today';
  if (whole === 1) return '1 day ago';
  if (whole < 90) return `${whole} days ago`;
  const months = Math.round(whole / 30.44);
  if (whole < 365) return `${months} months ago`;
  const years = whole / 365.25;
  return years < 2 ? `${years.toFixed(1)} years ago` : `${Math.round(years)} years ago`;
}

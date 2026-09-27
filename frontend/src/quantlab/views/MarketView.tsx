import { ChartLine, History, LineChart, ServerCrash, Shuffle } from 'lucide-react';
import { useCallback, useMemo } from 'react';
import type { Instrument } from '../../api/client';
import { replaceRoute, useRoute } from '../../chrome/router';
import { Button } from '../../components/ui/button';
import { ButtonGroup } from '../../components/ui/layout';
import { cn } from '../../lib/utils';
import { EmptyState } from '../chrome/EmptyState';
import { MarketChartCard } from '../market/MarketChartCard';
import {
  cellClasses,
  gridClasses,
  INTERVALS,
  MAX_TICKERS,
  RANGES,
  STUDIES,
  type DataMode,
  type Interval,
  type RangeId,
  type StudyId,
} from '../market/marketModel';
import { UniverseRail } from '../market/UniverseRail';
import {
  useChartSelection,
  useCustomUniverses,
  useInstrumentCatalog,
} from '../market/useMarketData';

const labelClass = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

/**
 * The view settings, in the address alongside the tickers, so a layout a
 * colleague sends is the layout they were looking at.
 */
function useMarketSettings() {
  const route = useRoute();
  const params = route.params;
  const mode: DataMode = params.get('data') === 'sim' ? 'simulated' : 'historical';
  const interval = (INTERVALS.find((i) => i.id === params.get('bar'))?.id ?? '1D') as Interval;
  const range = (RANGES.find((r) => r === params.get('range')) ?? '1Y') as RangeId;
  const rawStudies = params.get('studies');
  const studies = useMemo(
    () =>
      new Set(
        (rawStudies ?? '')
          .split(',')
          .filter((id): id is StudyId => STUDIES.some((s) => s.id === id)),
      ),
    [rawStudies],
  );

  const update = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(params);
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
      replaceRoute('market', next);
    },
    [params],
  );

  return {
    mode,
    interval,
    range,
    studies,
    setMode: (value: DataMode) => update('data', value === 'simulated' ? 'sim' : null),
    setInterval: (value: Interval) => update('bar', value === '1D' ? null : value),
    setRange: (value: RangeId) => update('range', value === '1Y' ? null : value),
    toggleStudy: (id: StudyId) => {
      const next = new Set(studies);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      update('studies', STUDIES.filter((s) => next.has(s.id)).map((s) => s.id).join(','));
    },
  };
}

function Segment<T extends string>({
  label,
  options,
  value,
  onChange,
  disabled,
  disabledTitle,
}: {
  label: string;
  options: { id: T; label: string; title?: string }[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  disabledTitle?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className={labelClass}>{label}</span>
      <ButtonGroup label={label} title={disabled ? disabledTitle : undefined}>
        {options.map((option) => (
          <Button
            key={option.id}
            type="button"
            size="sm"
            variant={value === option.id ? 'default' : 'outline'}
            aria-pressed={value === option.id}
            title={option.title}
            disabled={disabled}
            onClick={() => onChange(option.id)}
          >
            {option.label}
          </Button>
        ))}
      </ButtonGroup>
    </div>
  );
}

export function MarketView({
  instruments: fallback,
  feedError,
  rng,
}: {
  /** The shell's watchlist, used only if the full catalogue cannot be read. */
  instruments: Instrument[];
  feedError: string | null;
  rng?: () => number;
}) {
  const catalog = useInstrumentCatalog(fallback);
  const { selected, set, toggle, remove } = useChartSelection();
  const { universes, save, remove: removeUniverse } = useCustomUniverses();
  const settings = useMarketSettings();
  const historical = settings.mode === 'historical';

  const instruments = useMemo(
    () => (catalog.status === 'ready' ? catalog.data : []),
    [catalog],
  );
  const bySymbol = useMemo(() => new Map(instruments.map((i) => [i.symbol, i])), [instruments]);

  if (catalog.status === 'error') {
    return (
      <EmptyState
        testId="market-error"
        icon={ServerCrash}
        tone="error"
        title="Instruments unavailable"
        detail={feedError ?? catalog.message}
      />
    );
  }

  return (
    <div
      data-testid="market-view"
      className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,22rem)_minmax(0,1fr)] overflow-hidden lg:grid-cols-[300px_minmax(0,1fr)] lg:grid-rows-1"
    >
      <aside
        aria-label="Universe"
        className="flex min-h-0 flex-col border-b border-border bg-card lg:border-b-0 lg:border-r"
      >
        {catalog.status === 'loading' ? (
          <EmptyState icon={LineChart} title="Loading instruments…" role="status" />
        ) : instruments.length === 0 ? (
          <EmptyState
            testId="market-no-instruments"
            icon={LineChart}
            title="No instruments"
            detail="The warehouse has no instruments to chart yet."
          />
        ) : (
          <UniverseRail
            instruments={instruments}
            selected={selected}
            onToggle={toggle}
            onSet={set}
            universes={universes}
            onSaveUniverse={save}
            onDeleteUniverse={removeUniverse}
          />
        )}
      </aside>

      <div data-testid="market-workspace" className="flex min-h-0 min-w-0 flex-col">
        <div
          data-testid="market-toolbar"
          className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-2 border-b border-border px-4 py-2"
        >
          <Segment<DataMode>
            label="Data"
            value={settings.mode}
            onChange={settings.setMode}
            options={[
              { id: 'historical', label: 'Historical', title: 'Stored end-of-day bars from the warehouse' },
              { id: 'simulated', label: 'Simulated intraday', title: 'A random walk from the last close — not market data' },
            ]}
          />
          <Segment<Interval>
            label="Bar"
            value={settings.interval}
            onChange={settings.setInterval}
            disabled={!historical}
            disabledTitle="The simulation ticks once a second; bar size applies to historical data"
            options={INTERVALS.map((i) => ({ id: i.id, label: i.label, title: i.detail }))}
          />
          <Segment<RangeId>
            label="Range"
            value={settings.range}
            onChange={settings.setRange}
            disabled={!historical}
            disabledTitle="The simulation shows its last five minutes"
            options={RANGES.map((r) => ({ id: r, label: r, title: `Window ending at the latest stored bar: ${r}` }))}
          />
          <div className="flex flex-wrap items-center gap-2">
            <span className={labelClass}>Studies</span>
            <ButtonGroup label="Studies">
              {STUDIES.map((study) => {
                const unavailable = !historical && study.historicalOnly;
                const on = settings.studies.has(study.id) && !unavailable;
                return (
                  <Button
                    key={study.id}
                    type="button"
                    size="sm"
                    variant={on ? 'default' : 'outline'}
                    aria-pressed={on}
                    disabled={unavailable}
                    title={unavailable ? `${study.detail} — needs historical data` : study.detail}
                    onClick={() => settings.toggleStudy(study.id)}
                  >
                    {study.label}
                  </Button>
                );
              })}
            </ButtonGroup>
          </div>
        </div>

        {/* The one line that answers "is this real, and is it now?" -- on the
            page itself, not in a tooltip. */}
        <div
          data-testid="market-provenance"
          data-mode={settings.mode}
          role="note"
          className={cn(
            'flex shrink-0 items-center gap-2 border-b border-border px-4 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em]',
            historical ? 'text-primary' : 'bg-destructive/5 text-destructive',
          )}
        >
          {historical ? (
            <History size={16} strokeWidth={1.5} aria-hidden="true" />
          ) : (
            <Shuffle size={16} strokeWidth={1.5} aria-hidden="true" />
          )}
          {historical
            ? `Historical · end-of-day bars ingested from market data providers · each bar = ${INTERVALS.find((i) => i.id === settings.interval)?.detail.toLowerCase()} · not real-time`
            : 'Simulated · random walk seeded at the last stored close · 1 s ticks · not market data — QuantLab has no live feed'}
        </div>

        {selected.length === 0 ? (
          <EmptyState
            testId="market-no-selection"
            icon={ChartLine}
            title="Select a ticker to review market movements"
            detail={`Tick up to ${MAX_TICKERS} instruments in the universe list, or type tickers into Chart tickers and press GO. One chart fills the page; two sit side by side; three or four share a grid.`}
            className="min-h-0 flex-1"
          />
        ) : (
          <div
            data-testid="market-grid"
            data-count={selected.length}
            className={cn(
              'grid min-h-0 flex-1 gap-3 overflow-y-auto p-3 lg:overflow-hidden',
              gridClasses(selected.length),
            )}
          >
            {selected.map((symbol, index) => (
              <div
                key={symbol}
                data-testid="market-cell"
                className={cn('flex min-h-0 min-w-0 flex-col', cellClasses(index, selected.length))}
              >
                <MarketChartCard
                  symbol={symbol}
                  instrument={bySymbol.get(symbol)}
                  mode={settings.mode}
                  interval={settings.interval}
                  range={settings.range}
                  active={settings.studies}
                  onRemove={() => remove(symbol)}
                  rng={rng}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

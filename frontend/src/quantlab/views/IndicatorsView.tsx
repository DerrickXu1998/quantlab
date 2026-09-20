import { Activity, ChartLine, LineChart, ServerCrash } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { getPrices, type Instrument, type PriceBar } from '../../api/client';
import { navigate } from '../../chrome/router';
import { CandlestickChart } from '../../components/CandlestickChart';
import { Button } from '../../components/ui/button';
import { FillColumn, ScrollRegion } from '../../components/ui/layout';
import { StatusBadge } from '../../components/ui/status-badge';
import { MacdChart } from '../charts/MacdChart';
import { PriceChart } from '../charts/PriceChart';
import { RsiChart } from '../charts/RsiChart';
import { CascadeItem } from '../chrome/Cascade';
import { EmptyState } from '../chrome/EmptyState';
import { FlashNumber } from '../chrome/FlashNumber';
import { FloatingChips } from '../chrome/FloatingChips';
import { Panel } from '../chrome/Panel';
import {
  bollinger,
  BOLLINGER_MULT,
  BOLLINGER_PERIOD,
  lastValue,
  macd,
  MACD_FAST,
  MACD_SIGNAL,
  MACD_SLOW,
  rsi,
  RSI_PERIOD,
  vwap,
} from '../data/indicators';
import { useRollingSeries } from '../feed/useRollingSeries';
import { useTick } from '../feed/FeedProvider';
import { WatchlistRail } from '../panels/WatchlistRail';

type IndicatorId = 'rsi' | 'macd' | 'bollinger' | 'vwap';

const SIM_CHART =
  'The series is the simulated tick feed seeded from the real last close; indicators are computed from it in the browser.';
const SIM_VWAP =
  'The feed carries no volume, so VWAP weights every tick equally — a cumulative average price.';
const REAL_HISTORY =
  'Stored end-of-day bars from the active dataset — nothing here is simulated.';

/** Real stored bars for the daily-history view; null while loading. */
function useDailyBars(symbol: string | null, enabled: boolean): PriceBar[] | null {
  const [bars, setBars] = useState<PriceBar[] | null>(null);

  useEffect(() => {
    if (!symbol || !enabled) return;
    let cancelled = false;
    setBars(null);
    getPrices(symbol)
      .then((result) => {
        if (!cancelled) setBars(result.items);
      })
      .catch(() => {
        if (!cancelled) setBars([]);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, enabled]);

  return enabled ? bars : null;
}

/** A FloatingChips-styled toggle: same chip, but a button that switches state. */
function ToggleChip({
  label,
  active,
  onToggle,
  children,
}: {
  label: string;
  active: boolean;
  onToggle: () => void;
  children?: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      className={`pointer-events-auto flex items-center gap-1.5 rounded-sm border px-2 py-1 transition-colors ${
        active
          ? 'border-primary/50 bg-primary/10 text-primary'
          : 'border-border bg-card text-foreground hover:bg-accent/40'
      }`}
    >
      <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      {children}
    </button>
  );
}

function WarmingUp({ needed, have }: { needed: number; have: number }) {
  return (
    // Compact, and sized like the chart it stands in for: at the default
    // padding a warming-up sub-panel was taller than the price chart above it,
    // which inverts the hierarchy for the half-minute it takes to fill.
    <EmptyState
      icon={Activity}
      title={`Warming up — ${Math.max(0, needed - have)} more ticks`}
      role="status"
      className="py-6"
    />
  );
}

export function IndicatorsView({
  instruments,
  feedError,
}: {
  instruments: Instrument[];
  feedError: string | null;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [active, setActive] = useState<Set<IndicatorId>>(new Set());
  // 'ticks' is the simulated feed; 'daily' is the real stored history.
  const [mode, setMode] = useState<'ticks' | 'daily'>('ticks');
  const dailyBars = useDailyBars(selected, mode === 'daily');

  useEffect(() => {
    if (selected === null && instruments.length > 0) setSelected(instruments[0].symbol);
  }, [instruments, selected]);

  const series = useRollingSeries(selected);
  const tick = useTick(selected ?? '');

  const toggle = (id: IndicatorId) =>
    setActive((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Indicators recompute from the series on each tick; the series is bounded
  // at 240 points, so each of these is cheap.
  const bands = useMemo(
    () => (active.has('bollinger') ? bollinger(series) : null),
    [active, series],
  );
  const vwapSeries = useMemo(() => (active.has('vwap') ? vwap(series) : null), [active, series]);
  const rsiSeries = useMemo(() => (active.has('rsi') ? rsi(series) : null), [active, series]);
  const macdResult = useMemo(() => (active.has('macd') ? macd(series) : null), [active, series]);

  // %B: where the price sits inside its bands.
  const percentB = useMemo(() => {
    if (!bands) return null;
    const last = [...bands].reverse().find((band) => band.upper !== null);
    const price = series[series.length - 1];
    if (!last || price === undefined || last.upper === null || last.lower === null) return null;
    const width = last.upper - last.lower;
    return width === 0 ? null : (price - last.lower) / width;
  }, [bands, series]);

  if (feedError) {
    return (
      <EmptyState
        testId="indicators-feed-error"
        icon={ServerCrash}
        tone="error"
        title="Feed disconnected"
        detail={feedError}
      />
    );
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[240px_minmax(0,1fr)]">
      <CascadeItem index={0} className="hidden min-h-0 border-r border-border lg:flex lg:flex-col">
        <Panel title="Instruments" fill scroll className="border-0" bodyClassName="p-0">
          <WatchlistRail instruments={instruments} selected={selected} onSelect={setSelected} error={feedError} />
        </Panel>
      </CascadeItem>

      {/* A workspace, not a page. The chart takes the height the toggled-off
          sub-panels are not using, and this column only scrolls once RSI and
          MACD are both on and genuinely do not fit. */}
      <ScrollRegion testId="market-workspace" className="flex min-w-0 flex-col gap-4 p-4">
        {instruments.length === 0 ? (
          <EmptyState
            testId="indicators-empty"
            icon={LineChart}
            title="No instruments"
            detail="The watchlist is empty, so there is nothing to chart."
          />
        ) : selected === null ? (
          <EmptyState
            testId="indicators-no-selection"
            icon={ChartLine}
            title="Select an instrument"
            detail="Pick a symbol from the rail to chart its rolling series."
          />
        ) : (
          <>
            <CascadeItem index={1} className="relative flex min-h-[18rem] flex-1 flex-col">
              {mode === 'ticks' ? (
                <FloatingChips>
                  <ToggleChip
                    label={`RSI ${RSI_PERIOD}`}
                    active={active.has('rsi')}
                    onToggle={() => toggle('rsi')}
                  >
                    {active.has('rsi') ? (
                      <FlashNumber
                        value={rsiSeries ? lastValue(rsiSeries) : null}
                        format="ratio"
                        className="text-[11px]"
                      />
                    ) : null}
                  </ToggleChip>
                  <ToggleChip
                    label={`MACD ${MACD_FAST}·${MACD_SLOW}·${MACD_SIGNAL}`}
                    active={active.has('macd')}
                    onToggle={() => toggle('macd')}
                  >
                    {active.has('macd') ? (
                      <FlashNumber
                        value={macdResult ? lastValue(macdResult.histogram) : null}
                        format="price"
                        className="text-[11px]"
                      />
                    ) : null}
                  </ToggleChip>
                  <ToggleChip
                    label={`BB ${BOLLINGER_PERIOD}·${BOLLINGER_MULT}`}
                    active={active.has('bollinger')}
                    onToggle={() => toggle('bollinger')}
                  >
                    {active.has('bollinger') ? (
                      <FlashNumber value={percentB} format="ratio" className="text-[11px]" />
                    ) : null}
                  </ToggleChip>
                  <ToggleChip
                    label="VWAP"
                    active={active.has('vwap')}
                    onToggle={() => toggle('vwap')}
                  >
                    {active.has('vwap') ? (
                      <FlashNumber
                        value={vwapSeries ? lastValue(vwapSeries) : null}
                        format="price"
                        className="text-[11px]"
                      />
                    ) : null}
                  </ToggleChip>
                </FloatingChips>
              ) : null}

              <Panel
                fill
                title={mode === 'daily' ? `${selected} — daily history` : `${selected} — intraday`}
                className="border-0 pt-2"
                simulated={mode === 'ticks' ? SIM_CHART : undefined}
                actions={
                  <span className="flex items-center gap-2">
                    {mode === 'daily' ? (
                      <StatusBadge tone="good" title={REAL_HISTORY} testId="real-data-badge">
                        Real history
                      </StatusBadge>
                    ) : (
                      <FlashNumber
                        value={tick?.price}
                        format="price"
                        tone="accent"
                        className="text-[11px]"
                      />
                    )}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      aria-pressed={mode === 'daily'}
                      onClick={() => setMode(mode === 'daily' ? 'ticks' : 'daily')}
                    >
                      {mode === 'daily' ? 'Live ticks' : 'Daily history'}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate('research', { instrument: selected })}
                    >
                      Signals for {selected}
                    </Button>
                  </span>
                }
              >
                {mode === 'daily' ? (
                  dailyBars && dailyBars.length > 0 ? (
                    // Already `h-full`; it just needs a column that fills.
                    <FillColumn>
                      <CandlestickChart bars={dailyBars} autoSize />
                    </FillColumn>
                  ) : (
                    <EmptyState icon={Activity} title="Loading history…" role="status" />
                  )
                ) : (
                  <PriceChart fill series={series} bands={bands} vwap={vwapSeries} />
                )}
              </Panel>
            </CascadeItem>

            {mode === 'ticks' && active.has('rsi') && rsiSeries ? (
              <CascadeItem index={2} className="shrink-0">
                <Panel
                  title={`RSI (${RSI_PERIOD})`}
                  bodyClassName="p-0"
                  actions={
                    <FlashNumber
                      value={lastValue(rsiSeries)}
                      format="ratio"
                      className="text-[11px]"
                    />
                  }
                >
                  {lastValue(rsiSeries) === null ? (
                    <WarmingUp needed={RSI_PERIOD + 1} have={series.length} />
                  ) : (
                    <RsiChart values={rsiSeries} />
                  )}
                </Panel>
              </CascadeItem>
            ) : null}

            {mode === 'ticks' && active.has('macd') && macdResult ? (
              <CascadeItem index={3} className="shrink-0">
                <Panel
                  title={`MACD (${MACD_FAST}, ${MACD_SLOW}, ${MACD_SIGNAL})`}
                  bodyClassName="p-0"
                  actions={
                    <FlashNumber
                      value={lastValue(macdResult.histogram)}
                      format="price"
                      className="text-[11px]"
                    />
                  }
                >
                  {lastValue(macdResult.histogram) === null ? (
                    <WarmingUp needed={MACD_SLOW + MACD_SIGNAL} have={series.length} />
                  ) : (
                    <MacdChart macd={macdResult} />
                  )}
                </Panel>
              </CascadeItem>
            ) : null}

            {mode === 'ticks' && active.has('vwap') ? (
              <p className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                {SIM_VWAP}
              </p>
            ) : null}
          </>
        )}
      </ScrollRegion>
    </div>
  );
}

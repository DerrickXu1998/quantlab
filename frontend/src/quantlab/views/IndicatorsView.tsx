import { Activity, ChartLine, LineChart, ServerCrash } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { getPrices, type Instrument, type PriceBar } from '../../api/client';
import { navigate } from '../../chrome/router';
import { CandlestickChart } from '../../components/CandlestickChart';
import { Button } from '../../components/ui/button';
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
import { FundamentalsPanel } from '../panels/FundamentalsPanel';
import { WatchlistRail } from '../panels/WatchlistRail';
import { ValueLineChart } from '../charts/ValueLineChart';

type IndicatorId = 'rsi' | 'macd' | 'bollinger' | 'vwap';

const SIM_CHART =
  'The series is the simulated tick feed seeded from the real last close; indicators are computed from it in the browser.';
const SIM_VWAP =
  'The feed carries no volume, so VWAP weights every tick equally — a cumulative average price.';
const REAL_HISTORY =
  'Stored end-of-day bars from the active dataset — nothing here is simulated.';
const MACRO_SERIES =
  'A value series — yield, percent or index points — not a price. Shown as a line from stored daily bars; macro instruments are excluded from the simulated tick feed.';

/** Real stored bars for the daily-history view. */
type DailyBars =
  | { status: 'loading' }
  | { status: 'ready'; bars: PriceBar[] }
  | { status: 'error' };

/**
 * A failed read is an error state, never an empty series — an empty array here
 * used to render as "Loading history…" forever.
 */
function useDailyBars(symbol: string | null, enabled: boolean): DailyBars & { retry: () => void } {
  const [state, setState] = useState<DailyBars>({ status: 'loading' });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!symbol || !enabled) return;
    let cancelled = false;
    setState({ status: 'loading' });
    getPrices(symbol)
      .then((result) => {
        if (!cancelled) setState({ status: 'ready', bars: result.items });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, enabled, nonce]);

  return { ...state, retry: () => setNonce((n) => n + 1) };
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
      className={`pointer-events-auto flex items-center gap-1.5 rounded-sm border px-2 py-1 transition-colors focus-visible:outline-none focus-visible:border-primary ${
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
    <EmptyState
      icon={Activity}
      title={`Warming up — ${Math.max(0, needed - have)} more ticks`}
      role="status"
    />
  );
}

export function IndicatorsView({
  instruments,
  feedError,
  onFeedRetry,
}: {
  instruments: Instrument[];
  feedError: string | null;
  /** Offered on the feed-error state; absent in contexts that cannot retry. */
  onFeedRetry?: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [active, setActive] = useState<Set<IndicatorId>>(new Set());
  // 'ticks' is the simulated feed; 'daily' is the real stored history.
  const [mode, setMode] = useState<'ticks' | 'daily'>('ticks');

  const selectedInstrument = instruments.find((item) => item.symbol === selected) ?? null;
  // Macro series have no tick feed: the daily history is the only honest view.
  const isMacro = selectedInstrument?.kind === 'macro';
  const effectiveMode = isMacro ? 'daily' : mode;
  const dailyBars = useDailyBars(selected, effectiveMode === 'daily');

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
        action={
          onFeedRetry ? (
            <Button type="button" variant="outline" size="sm" onClick={onFeedRetry}>
              Retry
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)]">
      <CascadeItem index={0} className="border-b border-border lg:border-b-0 lg:border-r">
        <Panel title="Instruments" className="border-0" bodyClassName="p-0">
          <WatchlistRail instruments={instruments} selected={selected} onSelect={setSelected} error={feedError} />
        </Panel>
      </CascadeItem>

      <div className="min-w-0 overflow-y-auto p-4">
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
            <CascadeItem index={1} className="relative">
              {effectiveMode === 'ticks' ? (
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
                title={
                  effectiveMode === 'daily' ? `${selected} — daily history` : `${selected} — intraday`
                }
                className="border-0 pt-2"
                simulated={effectiveMode === 'ticks' ? SIM_CHART : undefined}
                actions={
                  <span className="flex items-center gap-2">
                    {isMacro ? (
                      <StatusBadge tone="idle" title={MACRO_SERIES} testId="macro-badge">
                        Macro series — value, not price
                      </StatusBadge>
                    ) : effectiveMode === 'daily' ? (
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
                    {isMacro ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled
                        title="Macro series have no simulated tick feed — daily history only."
                      >
                        Live ticks
                      </Button>
                    ) : (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        aria-pressed={effectiveMode === 'daily'}
                        onClick={() => setMode(mode === 'daily' ? 'ticks' : 'daily')}
                      >
                        {effectiveMode === 'daily' ? 'Live ticks' : 'Daily history'}
                      </Button>
                    )}
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
                {effectiveMode === 'daily' ? (
                  dailyBars.status === 'error' ? (
                    <EmptyState
                      testId="daily-history-error"
                      icon={ServerCrash}
                      tone="error"
                      title="History unavailable"
                      detail={`The stored daily bars for ${selected} could not be loaded.`}
                      action={
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={dailyBars.retry}
                        >
                          Retry
                        </Button>
                      }
                    />
                  ) : dailyBars.status === 'ready' && dailyBars.bars.length === 0 ? (
                    <EmptyState
                      icon={LineChart}
                      title="No stored bars"
                      detail={`The active dataset has no daily history for ${selected}.`}
                    />
                  ) : dailyBars.status === 'ready' ? (
                    isMacro ? (
                      // Degenerate OHLC (open=high=low=close=value, volume=0):
                      // candles and a volume pane would both be theatre.
                      <ValueLineChart
                        points={dailyBars.bars.map((bar) => ({ date: bar.date, value: bar.close }))}
                        height={320}
                        testId="macro-history-chart"
                      />
                    ) : (
                      <CandlestickChart bars={dailyBars.bars} autoSize />
                    )
                  ) : (
                    <EmptyState icon={Activity} title="Loading history…" role="status" />
                  )
                ) : (
                  <PriceChart series={series} bands={bands} vwap={vwapSeries} />
                )}
              </Panel>
            </CascadeItem>

            <CascadeItem index={4} className="mt-4">
              <FundamentalsPanel symbol={selected} />
            </CascadeItem>

            {effectiveMode === 'ticks' && active.has('rsi') && rsiSeries ? (
              <CascadeItem index={2} className="mt-4">
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

            {effectiveMode === 'ticks' && active.has('macd') && macdResult ? (
              <CascadeItem index={3} className="mt-4">
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

            {effectiveMode === 'ticks' && active.has('vwap') ? (
              <p className="mt-4 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                {SIM_VWAP}
              </p>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

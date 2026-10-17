import { Activity, Moon, PlugZap, ServerCrash, X } from 'lucide-react';
import { useMemo, type ReactNode } from 'react';
import type { Instrument } from '../../api/client';
import { navigate } from '../../chrome/router';
import { Button } from '../../components/ui/button';
import { StatusBadge, type StatusTone } from '../../components/ui/status-badge';
import { EmptyState } from '../chrome/EmptyState';
import { Panel } from '../chrome/Panel';
import type { LiveCardState } from '../feed/liveFeed';
import { MarketChart } from './MarketChart';
import {
  anchoredVwap,
  computeStudies,
  daysOld,
  formatAge,
  providerMix,
  INTERVAL_NOUN,
  nyClock,
  resample,
  sliceRange,
  tailStudies,
  weekday,
  type DataMode,
  type Interval,
  type RangeId,
  type StudyId,
} from './marketModel';
import { useDailyBars, useLiveSeries, useModelSignals } from './useMarketData';

export const HISTORICAL_NOTE =
  'Historical: end-of-day OHLCV bars ingested from the market data provider named under Source, stored as delivered. Nothing on this chart is simulated.';
export const SYNTHETIC_NOTE =
  'Synthetic: these bars were generated for testing, not ingested from a market data provider. They are not real prices.';
export const LIVE_NOTE =
  "Live: today's IBKR prices, 1-minute candles from the open with the newest one forming tick by tick (about one tick a second). Provisional and for display only: Tiingo's end-of-day load is the record, and no backtest reads these.";
export const FAKE_NOTE =
  'Fake feed: these frames come from scripts/live_fake_publish.py, the development stand-in for the IBKR collector. They are not market prices.';

/** How each live state is badged on the card. */
const LIVE_BADGE: Record<LiveCardState['kind'], { tone: StatusTone; label: string }> = {
  live: { tone: 'good', label: 'Live · IBKR' },
  waiting: { tone: 'active', label: 'Waiting for ticks' },
  connecting: { tone: 'active', label: 'Connecting' },
  stale: { tone: 'bad', label: 'Stale' },
  closed: { tone: 'idle', label: 'Market closed' },
  offline: { tone: 'bad', label: 'Feed offline' },
  not_subscribed: { tone: 'bad', label: 'Not subscribed' },
};

function Fact({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="flex items-baseline gap-1.5" data-testid={testId}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{children}</dd>
    </div>
  );
}

function ageOf(tickAt: number | null, now: number): string {
  if (tickAt === null) return '—';
  const seconds = Math.max(0, Math.round((now - tickAt) / 1000));
  return seconds < 60 ? `${seconds} s ago` : `${Math.round(seconds / 60)} min ago`;
}

export function MarketChartCard({
  symbol,
  instrument,
  mode,
  interval,
  range,
  active,
  onRemove,
}: {
  symbol: string;
  instrument?: Instrument;
  mode: DataMode;
  interval: Interval;
  range: RangeId;
  active: ReadonlySet<StudyId>;
  onRemove: () => void;
}) {
  const historical = mode === 'historical';
  const daily = useDailyBars(symbol);
  const allDaily = daily.status === 'ready' ? daily.data : null;
  const lastDaily = allDaily?.[allDaily.length - 1] ?? null;

  const signals = useModelSignals(symbol, historical && active.has('signals'));
  const live = useLiveSeries(symbol, !historical);

  const view = useMemo(() => {
    if (!historical || !allDaily) return null;
    const aggregated = resample(allDaily, interval);
    const bars = sliceRange(aggregated, range);
    // Studies run over the whole history so a 1M window does not open on a
    // 50-bar warm-up gap; then they are cut to the window.
    const studies = tailStudies(
      computeStudies(aggregated.map((bar) => bar.close), active),
      bars.length,
    );
    if (active.has('vwap')) studies.vwap = anchoredVwap(bars);
    return { bars, studies };
  }, [historical, allDaily, interval, range, active]);

  // Who supplied the bars in view -- counted on the daily bars, so a weekly
  // chart reports the same provider split as the daily one.
  const mix = useMemo(
    () => (allDaily ? providerMix(sliceRange(allDaily, range)) : null),
    [allDaily, range],
  );

  const liveStudies = useMemo(() => {
    if (historical) return {};
    const studies = computeStudies(live.candles.map((candle) => candle.close), active);
    // Anchored at the open: the session VWAP intraday traders mean by VWAP.
    if (active.has('vwap')) studies.vwap = anchoredVwap(live.candles);
    return studies;
  }, [historical, live.candles, active]);

  // Many warehouse names are the symbol again; "AAPL.US · AAPL.US" says nothing.
  const title =
    instrument && instrument.name && instrument.name !== symbol ? `${symbol} · ${instrument.name}` : symbol;
  const first = view?.bars[0];
  const last = view?.bars[view.bars.length - 1];
  const fake = !historical && live.feed.fake;
  const badge = LIVE_BADGE[live.state.kind];
  const now = Date.now();

  return (
    <Panel
      fill
      title={title}
      className="min-h-[360px]"
      bodyClassName="p-0"
      simulated={fake ? FAKE_NOTE : undefined}
      actions={
        <>
          {historical && mix?.synthetic ? (
            <StatusBadge tone="bad" title={SYNTHETIC_NOTE} testId="provenance-synthetic">
              Synthetic
            </StatusBadge>
          ) : historical ? (
            <StatusBadge tone="good" title={HISTORICAL_NOTE} testId="provenance-historical">
              Historical · EOD
            </StatusBadge>
          ) : (
            <StatusBadge
              tone={badge.tone}
              title={'detail' in live.state ? live.state.detail : LIVE_NOTE}
              testId="provenance-live"
            >
              <span data-state={live.state.kind}>
                {fake && live.state.kind === 'live' ? 'Live · FAKE feed' : badge.label}
              </span>
            </StatusBadge>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            title={`Open ${symbol}'s signals in Research`}
            onClick={() => navigate('research', { instrument: symbol })}
          >
            Signals
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${symbol} from the charts`}
            title="Remove from the charts"
            onClick={onRemove}
          >
            <X size={16} strokeWidth={1.5} aria-hidden="true" />
          </Button>
        </>
      }
    >
      {/* What the chart is, in words, before anyone has to hover. */}
      <dl
        data-testid="chart-facts"
        className="flex shrink-0 flex-wrap gap-x-4 gap-y-1 border-b border-border px-3 py-1.5 font-mono text-[11px] tabular-nums"
      >
        {historical ? (
          <>
            <Fact label="Source" testId="fact-source">
              {!mix ? (
                '—'
              ) : mix.providers.length === 0 ? (
                'Ingested EOD · provider not reported'
              ) : (
                <span title={HISTORICAL_NOTE}>
                  {mix.providers.length === 1
                    ? mix.providers[0].label
                    : mix.providers.map((p) => `${p.label} ${p.bars}`).join(' · ')}
                  {mix.synthetic ? ' (generated, not market data)' : ' (ingested EOD)'}
                </span>
              )}
            </Fact>
            <Fact label="Bar" testId="fact-bar">
              {INTERVAL_NOUN[interval]}
              {interval === '1D' ? '' : ' (from daily)'}
            </Fact>
            <Fact label="Window" testId="fact-window">
              {first && last ? `${first.date} → ${last.date}` : '—'}
            </Fact>
            <Fact label="Bars" testId="fact-count">{view ? view.bars.length.toLocaleString() : '—'}</Fact>
            {active.has('signals') ? (
              <Fact label="Signals" testId="fact-signals">
                {signals.filter((s) => first && s.date >= first.date).length}
              </Fact>
            ) : null}
            <Fact label="Latest" testId="fact-latest">
              {last ? `${weekday(last.date)} ${last.date} · ${formatAge(daysOld(last.date))}` : '—'}
            </Fact>
          </>
        ) : (
          <>
            <Fact label="Source" testId="fact-source">
              <span title={fake ? FAKE_NOTE : LIVE_NOTE}>
                {fake ? 'FAKE feed (dev) — not market data' : 'IBKR · live · provisional'}
              </span>
            </Fact>
            <Fact label="Bar" testId="fact-bar">1 min, updates each tick</Fact>
            <Fact label="Session" testId="fact-session">
              {live.view?.sessionDate ?? '—'}
            </Fact>
            <Fact label="Last" testId="fact-last">
              {live.quote?.last != null ? live.quote.last.toFixed(2) : '—'}
              {live.quote?.bid != null && live.quote?.ask != null
                ? ` (${live.quote.bid.toFixed(2)} × ${live.quote.ask.toFixed(2)})`
                : ''}
            </Fact>
            <Fact label="Tick" testId="fact-tick">{ageOf(live.view?.tickAt ?? null, now)}</Fact>
            <Fact label="Line" testId="fact-line">{live.view?.status ?? 'pending'}</Fact>
            <Fact label="Clock">
              {live.candles.length > 0 ? `ET · from ${nyClock(live.candles[0].time)}` : 'ET'}
            </Fact>
          </>
        )}
      </dl>

      {historical ? (
        daily.status === 'error' ? (
          <EmptyState
            icon={ServerCrash}
            tone="error"
            title={`No history for ${symbol}`}
            detail={daily.message}
            testId="chart-error"
          />
        ) : daily.status === 'loading' ? (
          <EmptyState icon={Activity} title={`Loading ${symbol}…`} role="status" testId="chart-loading" />
        ) : !lastDaily || !view ? (
          <EmptyState icon={Activity} title={`${symbol} has no stored bars`} testId="chart-empty" />
        ) : (
          <MarketChart
            mode="historical"
            symbol={symbol}
            bars={view.bars}
            studies={view.studies}
            active={active}
            signals={signals}
            interval={interval}
            fitKey={`${symbol}|${interval}|${range}`}
          />
        )
      ) : live.candles.length > 0 ? (
        <MarketChart
          mode="live"
          symbol={symbol}
          candles={live.candles}
          studies={liveStudies}
          active={active}
          interval={interval}
          fitKey={`${symbol}|live|${live.view?.sessionDate ?? ''}`}
        />
      ) : (
        <LiveEmpty symbol={symbol} state={live.state} sessionError={live.view?.sessionError ?? null} />
      )}
    </Panel>
  );
}

/** A live chart with nothing to draw yet: say which of the reasons it is. */
function LiveEmpty({
  symbol,
  state,
  sessionError,
}: {
  symbol: string;
  state: LiveCardState;
  sessionError: string | null;
}) {
  switch (state.kind) {
    case 'offline':
      return (
        <EmptyState icon={PlugZap} tone="error" title="Live feed offline" detail={state.detail} testId="live-offline" />
      );
    case 'not_subscribed':
      return (
        <EmptyState icon={PlugZap} tone="error" title={`${symbol} is not subscribed`} detail={state.detail} testId="live-not-subscribed" />
      );
    case 'closed':
      return (
        <EmptyState
          icon={Moon}
          title="Market closed"
          detail="No live session is stored for this symbol. Historical shows the record."
          testId="live-closed"
        />
      );
    case 'stale':
      return <EmptyState icon={Activity} tone="error" title="Live feed stale" detail={state.detail} testId="live-stale" />;
    default:
      return (
        <EmptyState
          icon={Activity}
          title={`Waiting for ${symbol}'s session…`}
          detail={sessionError ?? 'Backfilling the session from the open, then about one tick a second.'}
          role="status"
          testId="live-waiting"
        />
      );
  }
}

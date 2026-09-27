import { Activity, ServerCrash, X } from 'lucide-react';
import { useMemo, type ReactNode } from 'react';
import type { Instrument } from '../../api/client';
import { navigate } from '../../chrome/router';
import { Button } from '../../components/ui/button';
import { StatusBadge } from '../../components/ui/status-badge';
import { EmptyState } from '../chrome/EmptyState';
import { Panel } from '../chrome/Panel';
import { MarketChart } from './MarketChart';
import {
  anchoredVwap,
  computeStudies,
  daysOld,
  formatAge,
  providerMix,
  INTERVAL_NOUN,
  resample,
  sliceRange,
  tailStudies,
  weekday,
  type DataMode,
  type Interval,
  type RangeId,
  type StudyId,
} from './marketModel';
import { SIM_TICK_MS, useDailyBars, useModelSignals, useSimulatedSeries } from './useMarketData';

export const HISTORICAL_NOTE =
  'Historical: end-of-day OHLCV bars ingested from the market data provider named under Source, stored as delivered. Nothing on this chart is simulated.';
export const SYNTHETIC_NOTE =
  'Synthetic: these bars were generated for testing, not ingested from a market data provider. They are not real prices.';
export const SIM_NOTE =
  'Simulated: a random walk seeded at the last stored close, one point per second. QuantLab has no live feed; these are not market prices.';

function Fact({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="flex items-baseline gap-1.5" data-testid={testId}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{children}</dd>
    </div>
  );
}

export function MarketChartCard({
  symbol,
  instrument,
  mode,
  interval,
  range,
  active,
  onRemove,
  rng,
}: {
  symbol: string;
  instrument?: Instrument;
  mode: DataMode;
  interval: Interval;
  range: RangeId;
  active: ReadonlySet<StudyId>;
  onRemove: () => void;
  /** Injected for tests: a fixed walk. */
  rng?: () => number;
}) {
  const daily = useDailyBars(symbol);
  const historical = mode === 'historical';
  const allDaily = daily.status === 'ready' ? daily.data : null;
  const lastDaily = allDaily?.[allDaily.length - 1] ?? null;

  const signals = useModelSignals(symbol, historical && active.has('signals'));
  const sim = useSimulatedSeries(symbol, lastDaily?.close ?? null, !historical, rng);

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

  const simStudies = useMemo(
    () => (historical ? {} : computeStudies(sim.map((point) => point.value), active)),
    [historical, sim, active],
  );

  // Many warehouse names are the symbol again; "AAPL.US · AAPL.US" says nothing.
  const title =
    instrument && instrument.name && instrument.name !== symbol ? `${symbol} · ${instrument.name}` : symbol;
  const first = view?.bars[0];
  const last = view?.bars[view.bars.length - 1];

  return (
    <Panel
      fill
      title={title}
      className="min-h-[360px]"
      bodyClassName="p-0"
      simulated={historical ? undefined : SIM_NOTE}
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
            <StatusBadge tone="simulated" title={SIM_NOTE} testId="provenance-simulated">
              Not live
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
              <span className="uppercase">Simulated walk — not market data</span>
            </Fact>
            <Fact label="Tick" testId="fact-bar">{SIM_TICK_MS / 1000} s</Fact>
            <Fact label="Seed" testId="fact-seed">
              {lastDaily ? `close ${lastDaily.date} = ${lastDaily.close.toFixed(2)}` : '—'}
            </Fact>
            <Fact label="Points" testId="fact-count">{sim.length}</Fact>
            <Fact label="Clock">UTC</Fact>
          </>
        )}
      </dl>

      {daily.status === 'error' ? (
        <EmptyState
          icon={ServerCrash}
          tone="error"
          title={`No history for ${symbol}`}
          detail={daily.message}
          testId="chart-error"
        />
      ) : daily.status === 'loading' || (!historical && sim.length === 0 && lastDaily) ? (
        <EmptyState icon={Activity} title={`Loading ${symbol}…`} role="status" testId="chart-loading" />
      ) : !lastDaily ? (
        <EmptyState icon={Activity} title={`${symbol} has no stored bars`} testId="chart-empty" />
      ) : historical && view ? (
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
      ) : (
        <MarketChart
          mode="simulated"
          symbol={symbol}
          sim={sim}
          studies={simStudies}
          active={active}
          interval={interval}
          fitKey={`${symbol}|sim`}
        />
      )}
    </Panel>
  );
}

import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { CandlestickChart } from '../src/components/CandlestickChart';
import { PanelApiProvider } from '../src/components/usePanelSize';
import { ThemeProvider } from '../src/theme/ThemeProvider';
import { makeBar } from './fixtures';
import { createFakePanelApi } from './mocks/dockview-react';
import {
  createdCharts,
  createdMarkerPlugins,
  createdSeries,
  resetLightweightChartsMock,
  type MockSeries,
} from './mocks/lightweight-charts';

const bars = [
  makeBar({ date: '2024-03-14', open: 100, high: 103, low: 99, close: 101, volume: 1_000_000 }),
  makeBar({ date: '2024-03-15', open: 101, high: 106, low: 100, close: 104, volume: 1_500_000 }),
];

function renderChart(props: { bars: typeof bars; markerDate?: string }) {
  return render(
    <ThemeProvider>
      <CandlestickChart {...props} />
    </ThemeProvider>,
  );
}

function seriesOfType(seriesType: MockSeries['seriesType']): MockSeries {
  const series = createdSeries.find((candidate) => candidate.seriesType === seriesType);
  if (!series) throw new Error(`no ${seriesType} series was created`);
  return series;
}

describe('CandlestickChart', () => {
  beforeEach(() => {
    resetLightweightChartsMock();
  });

  it('renders a chart container and creates one chart', () => {
    renderChart({ bars });

    expect(screen.getByTestId('price-chart')).toBeInTheDocument();
    expect(createdCharts).toHaveLength(1);
  });

  it('passes OHLC data to the candlestick series', () => {
    renderChart({ bars });

    const candles = seriesOfType('Candlestick');
    expect(candles.setData).toHaveBeenCalledWith([
      { time: '2024-03-14', open: 100, high: 103, low: 99, close: 101 },
      { time: '2024-03-15', open: 101, high: 106, low: 100, close: 104 },
    ]);
  });

  it('passes volume data to a separate histogram series', () => {
    renderChart({ bars });

    const volume = seriesOfType('Histogram');
    const [volumeData] = volume.setData.mock.calls.at(-1) as [{ time: string; value: number }[]];
    expect(volumeData).toHaveLength(2);
    expect(volumeData[0]).toMatchObject({ time: '2024-03-14', value: 1_000_000 });
    expect(volumeData[1]).toMatchObject({ time: '2024-03-15', value: 1_500_000 });
  });

  it('marks the selected signal date on the chart and in the accessibility tree', () => {
    renderChart({ bars, markerDate: '2024-03-15' });

    const [markers] = createdMarkerPlugins;
    const [markerData] = markers.setMarkers.mock.calls.at(-1) as [{ time: string }[]];
    expect(markerData).toHaveLength(1);
    expect(markerData[0]).toMatchObject({ time: '2024-03-15' });

    expect(screen.getByTestId('signal-marker')).toHaveTextContent('2024-03-15');
  });

  it('sets no marker when markerDate matches no bar', () => {
    renderChart({ bars, markerDate: '2020-01-01' });

    const [markers] = createdMarkerPlugins;
    expect(markers.setMarkers).toHaveBeenLastCalledWith([]);
    expect(screen.queryByTestId('signal-marker')).not.toBeInTheDocument();
  });

  it('renders a no-data message instead of mounting a chart when there are no bars', () => {
    renderChart({ bars: [] });

    expect(screen.getByText(/no price history available/i)).toBeInTheDocument();
    expect(screen.queryByTestId('price-chart')).not.toBeInTheDocument();
    expect(createdCharts).toHaveLength(0);
  });

  it('updates the existing chart instead of recreating it when bars change', () => {
    const { rerender } = renderChart({ bars });
    const candles = seriesOfType('Candlestick');
    const callsAfterMount = candles.setData.mock.calls.length;

    rerender(
      <ThemeProvider>
        <CandlestickChart bars={[...bars, makeBar({ date: '2024-03-18', close: 108 })]} />
      </ThemeProvider>,
    );

    expect(createdCharts).toHaveLength(1);
    expect(candles.setData.mock.calls.length).toBeGreaterThan(callsAfterMount);
  });

  it('removes the chart on unmount', () => {
    const { unmount } = renderChart({ bars });
    const [chart] = createdCharts;

    unmount();

    expect(chart.remove).toHaveBeenCalled();
  });
});

describe('CandlestickChart panel sizing (FR-009)', () => {
  beforeEach(() => {
    resetLightweightChartsMock();
  });

  function renderInPanel(api: ReturnType<typeof createFakePanelApi>) {
    return render(
      <ThemeProvider>
        <PanelApiProvider value={api}>
          <CandlestickChart bars={bars} />
        </PanelApiProvider>
      </ThemeProvider>,
    );
  }

  it('resizes the chart when a visible panel changes dimensions', () => {
    const api = createFakePanelApi({ width: 600, height: 300, isVisible: true });
    renderInPanel(api);
    const [chart] = createdCharts;

    act(() => api._resize(900, 420));

    expect(chart.resize).toHaveBeenCalledWith(900, 420);
  });

  it('does not resize while the panel is hidden in an inactive tab', () => {
    const api = createFakePanelApi({ width: 600, height: 300, isVisible: true });
    renderInPanel(api);
    const [chart] = createdCharts;

    act(() => api._setVisible(false));
    chart.resize.mockClear();

    act(() => api._resize(1000, 500));

    expect(chart.resize).not.toHaveBeenCalled();
  });

  it('applies the size exactly once when the panel becomes visible again', () => {
    const api = createFakePanelApi({ width: 600, height: 300, isVisible: true });
    renderInPanel(api);
    const [chart] = createdCharts;

    act(() => api._setVisible(false));
    act(() => api._resize(1000, 500));
    chart.resize.mockClear();

    act(() => api._setVisible(true));

    expect(chart.resize).toHaveBeenCalledTimes(1);
    expect(chart.resize).toHaveBeenCalledWith(1000, 500);
  });

  it('does not recreate the chart or resend data when only the size changes', () => {
    const api = createFakePanelApi({ width: 600, height: 300, isVisible: true });
    renderInPanel(api);
    const candles = createdSeries.find((s) => s.seriesType === 'Candlestick')!;
    const setDataCalls = candles.setData.mock.calls.length;

    act(() => api._resize(900, 420));

    expect(createdCharts).toHaveLength(1);
    expect(createdCharts[0].remove).not.toHaveBeenCalled();
    expect(candles.setData.mock.calls.length).toBe(setDataCalls);
  });
});

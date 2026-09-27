import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import type { CatalogModel, ExecutionConfig, RunPerformanceV2 } from '../../src/api/types';
import { DEFAULT_EXECUTION, asCatalogModel } from '../../src/api/types';
import { BenchmarkPanel } from '../../src/quantlab/panels/BenchmarkPanel';
import { ExitBreakdown } from '../../src/quantlab/panels/ExitBreakdown';
import { ExecutionForm } from '../../src/strategies/ExecutionForm';
import { RequiresSeries } from '../../src/strategies/RequiresSeries';
import { makePerformance } from './fixtures';

/**
 * The AI-quant-book additions as a reader meets them: alpha/beta on the run
 * detail (F5/U3), the borrow line and field (F8), and the macro gate's data
 * dependency on the catalogue card (S6).
 */

const fit = {
  alpha: 0.042,
  beta: 0.62,
  r_squared: 0.48,
  correlation: 0.69,
  tracking_error: 0.11,
  information_ratio: 0.35,
  observations: 504,
};

describe('BenchmarkPanel', () => {
  it('shows alpha, beta and R² as the backend sent them, with a plain reading', () => {
    render(<BenchmarkPanel regression={fit} />);

    const panel = screen.getByRole('region', { name: 'Against buy & hold' });
    expect(panel).toHaveTextContent('+4.20%');
    expect(panel).toHaveTextContent('0.62');
    expect(panel).toHaveTextContent('0.48');
    expect(panel).toHaveTextContent('504');
    expect(screen.getByTestId('benchmark-reading')).toHaveTextContent(
      /about 62% as much as buy-and-hold.*part of its movement is that exposure/i,
    );
    // The benchmark is named for what it is.
    expect(screen.getByTestId('benchmark-reading')).toHaveTextContent(/not an index/i);
  });

  it('says why when the regression is not measurable, instead of printing a zero beta', () => {
    render(<BenchmarkPanel regression={null} />);
    expect(screen.getByTestId('benchmark-unmeasured')).toHaveTextContent(/at least 60/);
    expect(screen.queryByText('0.00')).toBeNull();
  });

  it('renders nothing for a backend that does not send the field', () => {
    const { container } = render(<BenchmarkPanel regression={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('borrow cost', () => {
  function perf(borrow?: number): RunPerformanceV2 {
    return {
      ...(makePerformance() as unknown as RunPerformanceV2),
      costs: { commission: 12, slippage: 3, ...(borrow === undefined ? {} : { borrow }) },
      exit_reasons: { signal: 2 },
    };
  }

  it('is itemised when the run paid it', () => {
    render(<ExitBreakdown performance={perf(250)} />);
    expect(screen.getByTestId('run-costs-borrow')).toHaveTextContent('250');
  });

  it('is absent from a long-only run rather than shown as a zero', () => {
    render(<ExitBreakdown performance={perf(0)} />);
    expect(screen.queryByTestId('run-costs-borrow')).toBeNull();
  });

  function Harness() {
    const [value, setValue] = useState<ExecutionConfig>(DEFAULT_EXECUTION);
    return (
      <>
        <ExecutionForm value={value} onChange={setValue} />
        <pre data-testid="config">{JSON.stringify(value)}</pre>
      </>
    );
  }

  it('is only asked for once shorts are allowed, and lands in the config', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.queryByLabelText(/short borrow/i)).toBeNull();

    await user.click(screen.getByLabelText(/allow shorts/i));
    const field = screen.getByLabelText(/short borrow/i);
    await user.clear(field);
    await user.type(field, '50');

    const config = JSON.parse(screen.getByTestId('config').textContent ?? '{}') as ExecutionConfig;
    expect(config.borrow_cost_bps).toBe(50);
  });
});

describe('macro gate dependency', () => {
  it('names the market series a rule reads', () => {
    const model = asCatalogModel({
      name: 'macro-risk-off',
      version: '1.0.0',
      parameters: [],
      lookback_days: 25,
      scale_class: 'scale_free',
      direction_semantics: 'gate',
      roles: ['filter'],
      requires_series: ['VIX.FRED', 'HYSPREAD.FRED'],
    } as never) as CatalogModel;
    render(<RequiresSeries model={model} testId="series" />);
    expect(
      within(screen.getByTestId('series')).getByText('VIX.FRED · HYSPREAD.FRED'),
    ).toBeInTheDocument();
  });

  it('says nothing for a single-instrument rule', () => {
    const model = asCatalogModel({
      name: 'sma-crossover',
      version: '1.0.0',
      parameters: [],
      lookback_days: 50,
      scale_class: 'price_scaled',
      direction_semantics: 'cross',
    } as never) as CatalogModel;
    const { container } = render(<RequiresSeries model={model} />);
    expect(container).toBeEmptyDOMElement();
  });
});

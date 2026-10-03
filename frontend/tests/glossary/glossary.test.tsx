import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { GlossaryButton } from '../../src/glossary/GlossaryButton';
import { paramUnit } from '../../src/glossary/params';
import { GlossaryFrequency, ParamTerm, Term } from '../../src/glossary/Term';
import { TERMS } from '../../src/glossary/terms';
import { barsAsTime, describeUnit } from '../../src/glossary/units';

describe('Term', () => {
  it('explains a term on hover, with its unit, and nothing until then', async () => {
    const user = userEvent.setup();
    render(<Term id="sharpe">Sharpe</Term>);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    await user.hover(screen.getByTestId('term-sharpe'));

    const tip = screen.getByRole('tooltip');
    expect(tip).toHaveTextContent('Sharpe ratio');
    expect(tip).toHaveTextContent(/annualised/i);
    expect(tip).toHaveTextContent(/Unit/);

    await user.unhover(screen.getByTestId('term-sharpe'));
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('opens on keyboard focus and closes on Escape', async () => {
    const user = userEvent.setup();
    render(<Term id="slippage" />);

    await user.tab();
    expect(screen.getByRole('tooltip')).toHaveTextContent(/basis points/i);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('carries its explanation for screen readers without a hidden copy', () => {
    render(<Term id="beta">Beta</Term>);
    expect(screen.getByTestId('term-beta')).toHaveAttribute(
      'aria-description',
      expect.stringContaining('moves with the benchmark'),
    );
  });

  it('reads bars as time at the bar size in use', async () => {
    const user = userEvent.setup();
    render(
      <GlossaryFrequency frequency="5m">
        <ParamTerm rule="stochastic-threshold" name="k_period" description="Window of %K, in bars." example={14} />
      </GlossaryFrequency>,
    );

    await user.hover(screen.getByTestId('param-term-k_period'));

    const tip = screen.getByRole('tooltip');
    expect(tip).toHaveTextContent('Window of %K, in bars.');
    expect(tip).toHaveTextContent('78 a session');
    expect(tip).toHaveTextContent('14 bars ≈ 70 min');
  });

  it("prefers a parameter's declared unit over the table", async () => {
    const user = userEvent.setup();
    render(
      <ParamTerm
        rule="margin-filter"
        name="min_margin"
        description="Minimum operating margin."
        declaredUnit="A percentage of revenue."
      />,
    );
    await user.hover(screen.getByTestId('param-term-min_margin'));
    expect(screen.getByRole('tooltip')).toHaveTextContent('A percentage of revenue.');
  });
});

describe('units', () => {
  it('turns bar counts into time for each bar size', () => {
    expect(barsAsTime(14, '5m')).toBe('≈ 70 min');
    expect(barsAsTime(14, '15m')).toBe('≈ 3.5 h');
    expect(barsAsTime(14, '1h')).toBe('≈ 2.2 sessions');
    expect(barsAsTime(14, '1d')).toBe('14 trading days');
  });

  it('says holding periods are trading days whatever the bars', () => {
    expect(describeUnit('trading-days', '5m')).toMatch(/never the next bar/);
  });

  it('knows the unit of a parameter by rule where names collide', () => {
    expect(paramUnit('stochastic-threshold', 'k_period')).toBe('bars');
    expect(paramUnit('adx-trend-filter', 'threshold')).toBe('level-0-100');
    expect(paramUnit('zscore-reversion', 'threshold')).toBe('std-devs');
    expect(paramUnit('macro-risk-off', 'hy_window')).toBe('trading-days');
  });

  it('gives every glossary term a label and a short explanation', () => {
    for (const [id, entry] of Object.entries(TERMS)) {
      expect(entry.label, id).toBeTruthy();
      expect(entry.short.length, id).toBeGreaterThan(20);
    }
  });
});

describe('Glossary', () => {
  it('lists every term, searchable, and returns focus when closed', async () => {
    const user = userEvent.setup();
    render(<GlossaryButton />);
    const button = screen.getByRole('button', { name: /glossary of terms/i });

    await user.click(button);
    const dialog = screen.getByRole('dialog', { name: /glossary/i });
    expect(within(dialog).getAllByRole('term').length).toBe(Object.keys(TERMS).length);

    await user.type(within(dialog).getByRole('searchbox', { name: /search terms/i }), 'drawdown');
    expect(within(dialog).getAllByRole('term').map((t) => t.textContent)).toEqual(['Max drawdown']);

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
});

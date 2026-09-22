import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  ButtonGroup,
  FillColumn,
  Measure,
  ScrollRegion,
  StatGrid,
} from '../src/components/ui/layout';
import { Panel } from '../src/quantlab/chrome/Panel';

/**
 * These primitives exist because the same four fitting faults kept recurring
 * across destinations. The tests pin the property that prevents each fault,
 * not the exact class list — `min-h-0` is load-bearing and gets dropped by
 * anyone tidying up class strings who does not know why it is there.
 */

describe('FillColumn', () => {
  it('can shrink below its content, so overflow scrolls instead of escaping', () => {
    render(
      <FillColumn>
        <span>child</span>
      </FillColumn>,
    );
    const column = screen.getByText('child').parentElement!;
    expect(column.className).toContain('min-h-0');
    expect(column.className).toContain('flex-1');
    expect(column.className).toContain('flex-col');
  });
});

describe('ScrollRegion', () => {
  it('scrolls rather than clipping, which is what stops a half-rendered row', () => {
    render(<ScrollRegion testId="region">rows</ScrollRegion>);
    const region = screen.getByTestId('region');
    expect(region.className).toContain('overflow-y-auto');
    // Without min-h-0 the region grows to its content and the scroll never
    // engages — the exact failure this primitive replaces.
    expect(region.className).toContain('min-h-0');
  });
});

describe('Measure', () => {
  it('caps the reading measure so content does not strand at the extremes', () => {
    const { container } = render(<Measure size="narrow">book</Measure>);
    const box = container.firstElementChild!;
    expect(box.className).toMatch(/max-w-/);
    expect(box.className).toContain('mx-auto');
  });

  it('can be left-aligned when the panel already provides the gutter', () => {
    const { container } = render(<Measure center={false}>book</Measure>);
    expect(container.firstElementChild!.className).not.toContain('mx-auto');
  });
});

describe('StatGrid', () => {
  it('packs columns to a readable density instead of stretching them', () => {
    const { container } = render(
      <StatGrid>
        <span>a</span>
      </StatGrid>,
    );
    const grid = container.firstElementChild as HTMLElement;
    // auto-fit + max-content: five stats across 1100px used to land one per
    // 220px with the label orphaned from its number.
    expect(grid.style.gridTemplateColumns).toContain('auto-fit');
    expect(grid.style.gridTemplateColumns).toContain('max-content');
  });
});

describe('ButtonGroup', () => {
  it('is one labelled group that wraps as a unit', () => {
    render(
      <ButtonGroup label="Speed">
        <button type="button">Fast</button>
      </ButtonGroup>,
    );
    const group = screen.getByRole('group', { name: 'Speed' });
    expect(group.className).toContain('flex-wrap');
  });
});

describe('Panel fill/scroll', () => {
  it('is a plain block by default, so existing callers are unaffected', () => {
    render(<Panel title="Plain">body</Panel>);
    const panel = screen.getByLabelText('Plain');
    expect(panel.className).not.toContain('flex-1');
  });

  it('fills its cell and lets the body take the slack', () => {
    render(
      <Panel title="Filled" fill>
        body
      </Panel>,
    );
    const panel = screen.getByLabelText('Filled');
    expect(panel.className).toContain('flex-1');
    expect(panel.className).toContain('min-h-0');

    const body = screen.getByText('body');
    expect(body.className).toContain('flex-1');
    expect(body.className).toContain('min-h-0');
  });

  it('scrolls the body when asked, never the header', () => {
    render(
      <Panel title="Scrolling" fill scroll>
        body
      </Panel>,
    );
    expect(screen.getByText('body').className).toContain('overflow-y-auto');
    // The header stays put: a title that scrolls away from its own table is
    // worse than no title.
    const header = screen.getByRole('heading', { name: /scrolling/i }).parentElement!;
    expect(header.className).toContain('shrink-0');
  });
});

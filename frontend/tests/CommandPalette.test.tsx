import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChartLine, Search } from 'lucide-react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandPalette, useCommandPaletteShortcut } from '../src/chrome/CommandPalette';
import type { NavItem } from '../src/chrome/MobileMenu';
import { installResizeObserver } from './mocks/resize-observer';

vi.mock('../src/research/company/useCompany', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/research/company/useCompany')>()),
  useInstruments: () => ({
    status: 'ready',
    message: null,
    reload: () => {},
    data: [
      { symbol: 'MSFT.US', name: 'Microsoft Corporation' },
      { symbol: 'AAPL.US', name: 'Apple Inc.' },
    ],
  }),
}));

installResizeObserver();
// cmdk scrolls the active row into view; jsdom has no layout to scroll.
Element.prototype.scrollIntoView = vi.fn();

const DESTINATIONS: NavItem[] = [
  { id: 'research', label: 'Research', icon: Search },
  { id: 'market', label: 'Market', icon: ChartLine },
];

function Harness() {
  const [open, setOpen] = useState(false);
  useCommandPaletteShortcut(() => setOpen((current) => !current));
  return <CommandPalette open={open} onOpenChange={setOpen} destinations={DESTINATIONS} />;
}

beforeEach(() => {
  window.location.hash = '';
});

describe('CommandPalette', () => {
  it('opens on Ctrl+K and lists the destinations before anything is typed', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.keyboard('{Control>}k{/Control}');

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /research/i })).toBeInTheDocument();
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
  });

  it('finds a company by name and opens it in Research under its stored symbol', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.keyboard('{Control>}k{/Control}');

    await user.type(screen.getByRole('combobox'), 'micro');
    // Shown short, routed whole.
    expect(screen.getAllByText('MSFT').length).toBeGreaterThan(0);
    await user.keyboard('{Enter}');

    expect(window.location.hash).toBe('#/research?symbol=MSFT.US');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('charts a company in Market from the second group', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.keyboard('{Control>}k{/Control}');
    await user.type(screen.getByRole('combobox'), 'aapl');

    const options = screen.getAllByRole('option', { name: /AAPL/ });
    await user.click(options[options.length - 1] as HTMLElement);

    expect(window.location.hash).toBe('#/market?symbols=AAPL.US');
  });
});

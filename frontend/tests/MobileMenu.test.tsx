import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ArrowLeftRight, LayoutDashboard, Search } from 'lucide-react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MobileHeader, type NavItem } from '../src/chrome/MobileMenu';
import { ThemeProvider } from '../src/theme/ThemeProvider';
import { mockSystemPrefersDark } from './mocks/match-media';

const ITEMS: NavItem[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'research', label: 'Research', icon: Search },
  {
    id: 'execution',
    label: 'Execution',
    icon: ArrowLeftRight,
    simulated: 'Everything in Execution is simulated.',
  },
];

function renderHeader(onNavigate = vi.fn()) {
  render(
    <ThemeProvider>
      <MobileHeader items={ITEMS} current="research" onNavigate={onNavigate} />
    </ThemeProvider>,
  );
  return onNavigate;
}

beforeEach(() => {
  mockSystemPrefersDark(false);
});

/**
 * The phone header was a row of seven unlabelled icons squeezed against the
 * brand. It is now the brand, the current page, and one menu button.
 */
describe('MobileHeader', () => {
  it('shows only the brand, the current page and the menu button when closed', () => {
    renderHeader();

    expect(screen.getByText('QuantLab')).toBeInTheDocument();
    expect(screen.getByText('Research')).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /switch to/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open menu' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });

  it('lists every destination with its label, the sim marker and the theme switch', async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(screen.getByRole('button', { name: 'Open menu' }));

    const nav = screen.getByRole('navigation', { name: 'Destinations' });
    for (const label of ['Overview', 'Research', 'Execution']) {
      expect(within(nav).getByRole('button', { name: new RegExp(label) })).toBeInTheDocument();
    }
    expect(within(nav).getByRole('button', { name: /execution/i })).toHaveTextContent('sim');
    expect(within(nav).getByRole('button', { name: /research/i })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(
      screen.getByRole('button', { name: /switch to (light|dark) mode/i }),
    ).toBeInTheDocument();
  });

  it('navigates and closes when a destination is picked', async () => {
    const user = userEvent.setup();
    const onNavigate = renderHeader();

    await user.click(screen.getByRole('button', { name: 'Open menu' }));
    await user.click(screen.getByRole('button', { name: /overview/i }));

    expect(onNavigate).toHaveBeenCalledWith('overview');
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('closes on Escape and on a tap outside, returning focus to the button', async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(screen.getByRole('button', { name: 'Open menu' }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open menu' })).toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Open menu' }));
    await user.click(screen.getByTestId('mobile-menu-backdrop'));
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });
});

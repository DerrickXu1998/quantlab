import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ThemeProvider } from '../src/theme/ThemeProvider';
import { ThemeToggle } from '../src/theme/ThemeToggle';
import { mockSystemPrefersDark } from './mocks/match-media';

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe('ThemeToggle', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('dark');
  });

  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('dark');
  });

  it('exposes a single button whose accessible name describes the action', () => {
    mockSystemPrefersDark(false);
    renderToggle();

    // First visit is dark, so the action on offer is the light theme.
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument();
  });

  it('switches the app to light mode and flips its own accessible name', async () => {
    mockSystemPrefersDark(false);
    const user = userEvent.setup();
    renderToggle();

    await user.click(screen.getByRole('button', { name: /switch to light mode/i }));

    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(screen.getByRole('button', { name: /switch to dark mode/i })).toBeInTheDocument();
  });

  it('switches back to dark mode on a second activation', async () => {
    mockSystemPrefersDark(true);
    const user = userEvent.setup();
    renderToggle();

    await user.click(screen.getByRole('button', { name: /switch to light mode/i }));
    await user.click(screen.getByRole('button', { name: /switch to dark mode/i }));

    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument();
  });

  it('is operable with the keyboard', async () => {
    mockSystemPrefersDark(false);
    const user = userEvent.setup();
    renderToggle();

    await user.tab();
    expect(screen.getByRole('button')).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });
});

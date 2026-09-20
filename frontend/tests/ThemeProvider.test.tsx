import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider, useTheme } from '../src/theme/ThemeProvider';
import { mockSystemPrefersDark } from './mocks/match-media';

const STORAGE_KEY = 'quantlab-theme';

function Probe() {
  const { theme, setTheme, toggleTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme-value">{theme}</span>
      <button onClick={() => setTheme('dark')}>set dark</button>
      <button onClick={toggleTheme}>toggle</button>
    </div>
  );
}

describe('ThemeProvider', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('dark');
  });

  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('dark');
  });

  it('defaults to dark on a first visit, whatever the system prefers', async () => {
    // The terminal palette is dark by design; the light theme is a stored
    // choice, not a system inheritance.
    mockSystemPrefersDark(false);

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('theme-value')).toHaveTextContent('dark'));
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('defaults to dark when the system prefers dark and nothing is stored', async () => {
    mockSystemPrefersDark(true);

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('theme-value')).toHaveTextContent('dark'));
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('applies the dark class and persists to localStorage when setTheme is called', async () => {
    mockSystemPrefersDark(false);
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await user.click(screen.getByText('set dark'));

    expect(screen.getByTestId('theme-value')).toHaveTextContent('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('dark');
  });

  it('toggleTheme flips the theme and persists it', async () => {
    mockSystemPrefersDark(false);
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    // First visit is dark; the first toggle chooses light.
    await user.click(screen.getByText('toggle'));
    expect(screen.getByTestId('theme-value')).toHaveTextContent('light');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('light');

    await user.click(screen.getByText('toggle'));
    expect(screen.getByTestId('theme-value')).toHaveTextContent('dark');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('dark');
  });

  it('a stored preference wins over the system preference on mount', async () => {
    mockSystemPrefersDark(true);
    window.localStorage.setItem(STORAGE_KEY, 'light');

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('theme-value')).toHaveTextContent('light'));
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('falls back to the dark default when the stored value is invalid', async () => {
    mockSystemPrefersDark(false);
    window.localStorage.setItem(STORAGE_KEY, 'not-a-theme');

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('theme-value')).toHaveTextContent('dark'));
  });

  it('throws a clear error when useTheme is used outside a ThemeProvider', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/useTheme must be used within a ThemeProvider/);
    consoleError.mockRestore();
  });
});

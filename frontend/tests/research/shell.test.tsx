import { act, render, renderHook, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MODE_DEFINITIONS,
  ResearchPanel,
  ResearchShell,
} from '../../src/research/shell/ResearchShell';
import {
  DEFAULT_MODE,
  RESEARCH_MODES,
  useResearchRoute,
} from '../../src/research/shell/useResearchRoute';

beforeEach(() => {
  window.location.hash = '#/research';
});
afterEach(() => {
  window.location.hash = '';
});

describe('useResearchRoute', () => {
  it('opens on Company, the mode whose first action needs no explanation', () => {
    const { result } = renderHook(() => useResearchRoute());

    expect(result.current.mode).toBe('company');
    expect(DEFAULT_MODE).toBe('company');
    expect(result.current.symbol).toBeNull();
  });

  it('round-trips every mode through the address bar', () => {
    for (const mode of RESEARCH_MODES) {
      const { result } = renderHook(() => useResearchRoute());

      act(() => result.current.setMode(mode));

      expect(renderHook(() => useResearchRoute()).result.current.mode).toBe(mode);
    }
  });

  it('makes a company a bookmark', () => {
    window.location.hash = '#/research?mode=company&symbol=CAT.US';

    const { result } = renderHook(() => useResearchRoute());

    expect(result.current.symbol).toBe('CAT.US');
  });

  /**
   * The Market destination has linked to `?instrument=` since before this
   * change. Those links are in users' histories, so the parameter is read as
   * an alias rather than retired.
   */
  it('still honours the Market destination’s ?instrument= handoff', () => {
    window.location.hash = '#/research?instrument=MSFT.US';

    const { result } = renderHook(() => useResearchRoute());

    expect(result.current.symbol).toBe('MSFT.US');
  });

  it('walks the user to Company when a name is picked from a screen', () => {
    window.location.hash = '#/research?mode=screen';
    const { result } = renderHook(() => useResearchRoute());

    act(() => result.current.selectSymbol('JPM.US'));

    const after = renderHook(() => useResearchRoute()).result.current;
    expect(after.mode).toBe('company');
    expect(after.symbol).toBe('JPM.US');
  });

  /**
   * Switching mode adjusts the view; it is not travel. If every tab press
   * pushed a history entry, Back would walk the user through their own
   * clicks instead of returning them to where they came from.
   */
  it('does not push a history entry for a mode switch', () => {
    const before = window.history.length;
    const { result } = renderHook(() => useResearchRoute());

    act(() => result.current.setMode('company'));
    act(() => result.current.setMode('screen'));

    expect(window.history.length).toBe(before);
  });
});

describe('ResearchShell', () => {
  /**
   * The reported complaint was that panels did not say what they did. These
   * two tests are the regression guard on the fix: if a mode or a panel can
   * render without its purpose visible, the destination has regressed to what
   * was reported.
   */
  it('states on screen what the active mode is for', () => {
    render(
      <ResearchShell mode="screen" onModeChange={vi.fn()}>
        <div />
      </ResearchShell>,
    );

    expect(screen.getByText(MODE_DEFINITIONS.screen.purpose)).toBeInTheDocument();
  });

  it('offers all three modes and marks the active one', () => {
    render(
      <ResearchShell mode="company" onModeChange={vi.fn()}>
        <div />
      </ResearchShell>,
    );

    for (const mode of RESEARCH_MODES) {
      expect(screen.getByRole('tab', { name: MODE_DEFINITIONS[mode].label })).toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { selected: true })).toHaveAccessibleName('Ticker');
  });

  it('switches mode on click', async () => {
    const onModeChange = vi.fn();
    render(
      <ResearchShell mode="company" onModeChange={onModeChange}>
        <div />
      </ResearchShell>,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Screen' }));

    expect(onModeChange).toHaveBeenCalledWith('screen');
  });

  it('mounts only the active mode', () => {
    render(
      <ResearchShell mode="company" onModeChange={vi.fn()}>
        <p>only me</p>
      </ResearchShell>,
    );

    expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
    expect(screen.getByText('only me')).toBeInTheDocument();
  });
});

describe('ResearchPanel', () => {
  it('renders its purpose beside its title', () => {
    render(
      <ResearchPanel title="As filed" purpose="The accounts public on this date.">
        <div />
      </ResearchPanel>,
    );

    expect(screen.getByRole('heading', { name: /as filed/i })).toBeInTheDocument();
    expect(screen.getByText('The accounts public on this date.')).toBeInTheDocument();
  });
});

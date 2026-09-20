import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../src/api/client';
import { ThemeProvider } from '../src/theme/ThemeProvider';
import { RunsProvider } from '../src/runs/RunsContext';
import { Workspace } from '../src/workspace/Workspace';
import { WorkspaceProvider } from '../src/workspace/WorkspaceContext';
import { LAYOUT_STORAGE_KEY, saveLayout } from '../src/workspace/layoutStorage';
import { makeInstrument, makeSignal } from './fixtures';
import { createdDockviewApis, mockControls, resetDockviewMock } from './mocks/dockview-react';

vi.mock('../src/api/client');

function renderWorkspace() {
  return render(
    <ThemeProvider>
      <WorkspaceProvider>
        <RunsProvider>
          <Workspace />
        </RunsProvider>
      </WorkspaceProvider>
    </ThemeProvider>,
  );
}

describe('Workspace', () => {
  beforeEach(() => {
    resetDockviewMock();
    window.localStorage.clear();
    vi.mocked(apiClient.listInstruments).mockResolvedValue({
      total: 1,
      items: [makeInstrument()],
    });
    vi.mocked(apiClient.listSignals).mockResolvedValue({ total: 1, items: [makeSignal()] });
    vi.mocked(apiClient.getPrices).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(apiClient.listModels).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('renders every registered panel', async () => {
    renderWorkspace();

    expect(await screen.findByTestId('panel-filters')).toBeInTheDocument();
    expect(screen.getByTestId('panel-signals')).toBeInTheDocument();
    expect(screen.getByTestId('panel-chart')).toBeInTheDocument();
  });

  it('builds the default layout when nothing is stored', async () => {
    renderWorkspace();

    await waitFor(() => expect(createdDockviewApis).toHaveLength(1));
    const [api] = createdDockviewApis;
    expect(api.fromJSON).not.toHaveBeenCalled();
    expect(api.addPanel).toHaveBeenCalled();
  });

  it('restores a stored layout instead of building the default', async () => {
    saveLayout({ grid: {}, panels: {} });
    renderWorkspace();

    await waitFor(() => expect(createdDockviewApis).toHaveLength(1));
    const [api] = createdDockviewApis;
    await waitFor(() => expect(api.fromJSON).toHaveBeenCalled());
  });

  it('falls back to the default layout when a stored layout cannot be applied', async () => {
    saveLayout({ grid: {}, panels: {} });
    mockControls.fromJSONThrows = true;

    renderWorkspace();

    await waitFor(() => expect(createdDockviewApis).toHaveLength(1));
    const [api] = createdDockviewApis;
    await waitFor(() => expect(api.fromJSON).toHaveBeenCalled());
    // The workspace is cleared and rebuilt rather than left half-restored.
    expect(api.clear).toHaveBeenCalled();
    expect(api.addPanel).toHaveBeenCalled();
    // And the unusable payload is not left behind to fail again next load.
    expect(window.localStorage.getItem(LAYOUT_STORAGE_KEY)).toBeNull();
  });

  it('persists the layout when it changes', async () => {
    vi.useFakeTimers();
    try {
      renderWorkspace();
      await vi.waitFor(() => expect(createdDockviewApis).toHaveLength(1));
      const [api] = createdDockviewApis;

      api._fireLayoutChange();
      await vi.advanceTimersByTimeAsync(1000);

      expect(api.toJSON).toHaveBeenCalled();
      expect(window.localStorage.getItem(LAYOUT_STORAGE_KEY)).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('debounces rapid layout changes into a single write', async () => {
    vi.useFakeTimers();
    try {
      renderWorkspace();
      await vi.waitFor(() => expect(createdDockviewApis).toHaveLength(1));
      const [api] = createdDockviewApis;
      api.toJSON.mockClear();

      // Simulates a divider drag, which fires this event continuously.
      for (let i = 0; i < 25; i += 1) api._fireLayoutChange();
      await vi.advanceTimersByTimeAsync(1000);

      expect(api.toJSON).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('offers a way back for a closed panel', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    await waitFor(() => expect(createdDockviewApis).toHaveLength(1));
    const [api] = createdDockviewApis;

    // Simulate the user closing the chart panel.
    api.removePanel({ id: 'chart' });
    api._fireLayoutChange();

    const reopen = await screen.findByRole('button', { name: /reopen price/i });
    await user.click(reopen);

    expect(api.addPanel).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'chart', component: 'chart' }),
    );
  });
});

describe('Workspace floating panels (FR-013)', () => {
  beforeEach(() => {
    resetDockviewMock();
    window.localStorage.clear();
    vi.mocked(apiClient.listInstruments).mockResolvedValue({
      total: 1,
      items: [makeInstrument()],
    });
    vi.mocked(apiClient.listSignals).mockResolvedValue({ total: 1, items: [makeSignal()] });
    vi.mocked(apiClient.getPrices).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(apiClient.listModels).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
  });

  it('floats a panel through a keyboard-operable control, not drag alone', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    await waitFor(() => expect(createdDockviewApis).toHaveLength(1));
    const [api] = createdDockviewApis;

    const float = await screen.findByRole('button', { name: /float price panel/i });
    await user.click(float);

    expect(api.addFloatingGroup).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'chart' }),
      expect.anything(),
    );
  });
});

/**
 * A dock cell is whatever height the user last dragged it to. Panel content
 * that takes its natural height leaves a void; content that overflows gets cut
 * by the cell boundary. Both were live defects: a void under the filter form, a
 * signal table sliced through its second row, and a run form whose Instruments
 * control sat below the fold with no way to reach it.
 */
describe('Workspace panel fitting', () => {
  beforeEach(() => {
    resetDockviewMock();
    window.localStorage.clear();
    vi.mocked(apiClient.listInstruments).mockResolvedValue({
      total: 1,
      items: [makeInstrument()],
    });
    vi.mocked(apiClient.listSignals).mockResolvedValue({ total: 1, items: [makeSignal()] });
    vi.mocked(apiClient.getPrices).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(apiClient.listModels).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(apiClient.listRuns).mockResolvedValue({ total: 0, items: [] });
  });

  it('fills each cell and scrolls inside it rather than clipping at its edge', async () => {
    renderWorkspace();

    for (const id of ['filters', 'catalog']) {
      const column = (await screen.findByTestId(`panel-${id}`))
        .firstElementChild as HTMLElement;
      expect(column.className).toContain('h-full');
      const region = column.firstElementChild as HTMLElement;
      expect(region.className).toContain('overflow-y-auto');
      // The line everyone deletes while tidying: without it the region grows
      // to its content and the scroll never engages.
      expect(region.className).toContain('min-h-0');
    }
  });

  it('centres a panel that has nothing to show in its cell', async () => {
    renderWorkspace();

    // Run and Results both start empty; an empty state that takes its natural
    // height sits at the top of the cell with a void beneath it.
    for (const id of ['runConfig', 'runResults']) {
      const root = (await screen.findByTestId(`panel-${id}`)).firstElementChild as HTMLElement;
      expect(root.className).toContain('h-full');
      expect(root.className).toContain('justify-center');
    }
  });

  it('gives every panel a floor so a sash cannot crush it to nothing', async () => {
    renderWorkspace();

    await waitFor(() => expect(createdDockviewApis).toHaveLength(1));
    const [api] = createdDockviewApis;

    for (const id of ['filters', 'signals', 'chart', 'catalog', 'runConfig', 'runResults']) {
      expect(api.addPanel).toHaveBeenCalledWith(
        expect.objectContaining({ id, minimumHeight: expect.any(Number) }),
      );
    }
  });

  it('spends the column on the signal table, not on a void under the filters', async () => {
    renderWorkspace();

    await waitFor(() => expect(createdDockviewApis).toHaveLength(1));
    const [api] = createdDockviewApis;

    // The filter form is a fixed set of controls, so its row is sized to them
    // and the table keeps the rest of the column.
    const filters = api.panels.find((panel) => panel.id === 'filters')!;
    expect(filters.api.setSize).toHaveBeenCalledWith(
      expect.objectContaining({ height: expect.any(Number) }),
    );
    const signals = api.panels.find((panel) => panel.id === 'signals')!;
    expect(signals.api.setSize).not.toHaveBeenCalled();
  });
});

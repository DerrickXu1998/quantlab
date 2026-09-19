import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../src/api/client';
import { ThemeProvider } from '../src/theme/ThemeProvider';
import { WorkbenchProvider } from '../src/workbench/WorkbenchContext';
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
        <WorkbenchProvider>
          <Workspace />
        </WorkbenchProvider>
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

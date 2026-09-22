import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PanelApiProvider, usePanelSize } from '../src/components/usePanelSize';
import { createFakePanelApi } from './mocks/panel-api';

function Probe() {
  const { width, height, isVisible } = usePanelSize();
  return (
    <div>
      <span data-testid="size">
        {width}x{height}
      </span>
      <span data-testid="visible">{String(isVisible)}</span>
    </div>
  );
}

describe('usePanelSize', () => {
  it('seeds from the panel api on mount', () => {
    const api = createFakePanelApi({ width: 640, height: 300, isVisible: true });

    render(
      <PanelApiProvider value={api}>
        <Probe />
      </PanelApiProvider>,
    );

    expect(screen.getByTestId('size')).toHaveTextContent('640x300');
    expect(screen.getByTestId('visible')).toHaveTextContent('true');
  });

  it('updates when the panel reports new dimensions', () => {
    const api = createFakePanelApi({ width: 640, height: 300 });

    render(
      <PanelApiProvider value={api}>
        <Probe />
      </PanelApiProvider>,
    );

    act(() => api._resize(900, 420));

    expect(screen.getByTestId('size')).toHaveTextContent('900x420');
  });

  it('reflects visibility changes, as when a panel moves to an inactive tab', () => {
    const api = createFakePanelApi({ isVisible: true });

    render(
      <PanelApiProvider value={api}>
        <Probe />
      </PanelApiProvider>,
    );

    act(() => api._setVisible(false));
    expect(screen.getByTestId('visible')).toHaveTextContent('false');

    act(() => api._setVisible(true));
    expect(screen.getByTestId('visible')).toHaveTextContent('true');
  });

  it('unsubscribes from both panel events on unmount', () => {
    const api = createFakePanelApi();

    const { unmount } = render(
      <PanelApiProvider value={api}>
        <Probe />
      </PanelApiProvider>,
    );
    unmount();

    // Firing after unmount must not reach a disposed listener.
    expect(() => {
      api._resize(100, 100);
      api._setVisible(false);
    }).not.toThrow();
  });

  it('returns a usable default outside a dock panel rather than throwing', () => {
    expect(() => render(<Probe />)).not.toThrow();
    expect(screen.getByTestId('visible')).toHaveTextContent('true');
  });
});

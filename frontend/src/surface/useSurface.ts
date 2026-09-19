import { useCallback, useSyncExternalStore } from 'react';

/**
 * Which top-level surface is showing.
 *
 * A hash, not a router. There are exactly two surfaces, no nested routes and
 * no path parameters; pulling in react-router would add a dependency and force
 * every existing test that mounts App into a MemoryRouter for no gain. The
 * hash still gives deep links and a working back button.
 */
export type Surface = 'signals' | 'lab';

export const SURFACE_HASH: Record<Surface, string> = {
  signals: '#/',
  lab: '#/lab',
};

function read(): Surface {
  return window.location.hash.replace(/^#\/?/, '').split('?')[0] === 'lab' ? 'lab' : 'signals';
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange);
  return () => window.removeEventListener('hashchange', onChange);
}

export function useSurface(): { surface: Surface; setSurface: (next: Surface) => void } {
  // getServerSnapshot is the same read: there is no SSR here, but useSyncExternalStore
  // insists on one and hydration must not disagree with the client.
  const surface = useSyncExternalStore(subscribe, read, () => 'signals' as Surface);

  const setSurface = useCallback((next: Surface) => {
    window.location.hash = SURFACE_HASH[next];
  }, []);

  return { surface, setSurface };
}

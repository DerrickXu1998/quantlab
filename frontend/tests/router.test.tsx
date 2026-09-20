import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { hashFor, navigate, replaceRoute, useRoute } from '../src/chrome/router';

function fireHashchange() {
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

beforeEach(() => {
  window.location.hash = '';
});
afterEach(() => {
  window.location.hash = '';
});

describe('hash router', () => {
  it('defaults to Overview when there is no hash', () => {
    const { result } = renderHook(() => useRoute());

    expect(result.current.destination).toBe('overview');
  });

  it('deep-links each of the six destinations', () => {
    for (const destination of ['overview', 'research', 'strategies', 'replay', 'market', 'execution']) {
      window.location.hash = `#/${destination}`;

      const { result } = renderHook(() => useRoute());

      expect(result.current.destination).toBe(destination);
      expect(result.current.canonical).toBe(true);
    }
  });

  it('follows the hash changing under it, which is what back/forward does', async () => {
    const { result } = renderHook(() => useRoute());

    act(() => navigate('market'));
    await waitFor(() => expect(result.current.destination).toBe('market'));

    // The back button is a hashchange to the previous entry.
    act(() => {
      window.location.hash = '#/overview';
      fireHashchange();
    });
    await waitFor(() => expect(result.current.destination).toBe('overview'));
  });

  it('carries handoff params on the hash', async () => {
    const { result } = renderHook(() => useRoute());

    act(() => navigate('research', { instrument: 'ZZTRND' }));

    await waitFor(() => expect(result.current.destination).toBe('research'));
    expect(result.current.params.get('instrument')).toBe('ZZTRND');
    expect(window.location.hash).toBe('#/research?instrument=ZZTRND');
  });

  it('maps the legacy hashes instead of strand­ing old links', () => {
    window.location.hash = '#/lab';
    let route = renderHook(() => useRoute()).result.current;
    expect(route.destination).toBe('overview');
    expect(route.canonical).toBe(false);

    window.location.hash = '#/nonsense';
    route = renderHook(() => useRoute()).result.current;
    expect(route.destination).toBe('overview');
    expect(route.canonical).toBe(false);
  });

  it('canonicalises a legacy hash in place, with no new history entry', async () => {
    window.location.hash = '#/lab';
    const { result } = renderHook(() => useRoute());

    act(() => replaceRoute(result.current.destination, result.current.params));

    expect(window.location.hash).toBe('#/overview');
    await waitFor(() => expect(result.current.canonical).toBe(true));
  });

  it('round-trips params through hashFor', () => {
    const hash = hashFor('strategies', { model: 'sma-crossover', p_fast: '50' });
    expect(hash).toBe('#/strategies?model=sma-crossover&p_fast=50');
  });
});

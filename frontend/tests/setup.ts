import '@testing-library/jest-dom/vitest';
import { beforeEach, vi } from 'vitest';

// The real library renders to <canvas>, which jsdom does not implement, so every
// test that mounts a chart runs against the fake in tests/mocks/lightweight-charts.ts.
vi.mock('lightweight-charts', async () => import('./mocks/lightweight-charts'));

// Research keeps reads and applied models at module scope so they survive a
// trip to another tab. Tests must not inherit each other's. Imported lazily:
// a static import here would load the real API client before a test file's
// vi.mock of it applies, binding the hooks to the unmocked module.
beforeEach(async () => {
  const [{ clearReadCache }, { clearOverlayStore }] = await Promise.all([
    import('../src/research/company/useCompany'),
    import('../src/research/company/useModelOverlays'),
  ]);
  clearReadCache();
  clearOverlayStore();
});

import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// The real library renders to <canvas>, which jsdom does not implement, so every
// test that mounts a chart runs against the fake in tests/mocks/lightweight-charts.ts.
vi.mock('lightweight-charts', async () => import('./mocks/lightweight-charts'));

// dockview lays out from real element dimensions; jsdom reports every box as 0x0.
vi.mock('dockview-react', async () => import('./mocks/dockview-react'));

import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../src/api/client';
import { DatasetBadge } from '../src/workbench/DatasetBadge';

vi.mock('../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return { ...actual, getHealth: vi.fn() };
});

beforeEach(() => vi.clearAllMocks());

describe('DatasetBadge', () => {
  it('reports the warehouse when the backend says so', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue({
      status: 'ok',
      dataset: 'warehouse',
      seeded: true,
      signal_count: 10,
    });

    render(<DatasetBadge />);

    expect(await screen.findByTestId('dataset-badge')).toHaveTextContent(/live history/i);
  });

  it('marks the synthetic dataset plainly', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue({
      status: 'ok',
      dataset: 'sqlite',
      seeded: true,
      signal_count: 933,
    });

    render(<DatasetBadge />);

    const badge = await screen.findByTestId('dataset-badge');
    expect(badge).toHaveTextContent(/demo data/i);
    expect(badge).toHaveAttribute('title', expect.stringMatching(/synthetic/i));
  });

  it('never infers the dataset from the data itself', async () => {
    // A seeded, populated response that is nonetheless the demo: only the
    // reported dataset decides, not the presence of signals.
    vi.mocked(apiClient.getHealth).mockResolvedValue({
      status: 'ok',
      dataset: 'sqlite',
      seeded: true,
      signal_count: 50_000,
    });

    render(<DatasetBadge />);

    expect(await screen.findByTestId('dataset-badge')).toHaveTextContent(/demo data/i);
  });

  it('distinguishes "cannot reach the data" from "no data"', async () => {
    vi.mocked(apiClient.getHealth).mockRejectedValue(new apiClient.ApiError(0, 'unreachable'));

    render(<DatasetBadge />);

    const badge = await screen.findByTestId('dataset-badge');
    expect(badge).toHaveAttribute('role', 'alert');
    expect(badge).toHaveTextContent(/unreachable/i);
  });
});

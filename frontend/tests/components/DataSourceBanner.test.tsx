import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DatasetProvider } from '../../src/api/DatasetProvider';
import { DataSourceBanner } from '../../src/components/DataSourceBanner';
import type { Health } from '../../src/api/types';

const getHealth = vi.fn();

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    getHealth: () => getHealth(),
  };
});

function renderWithHealth(health: Health | null) {
  if (health === null) {
    getHealth.mockRejectedValue(new Error('unreachable'));
  } else {
    getHealth.mockResolvedValue(health);
  }
  return render(
    <DatasetProvider>
      <DataSourceBanner />
    </DatasetProvider>,
  );
}

describe('DataSourceBanner', () => {
  it('renders a demo strip for the synthetic dataset', async () => {
    renderWithHealth({ status: 'ok', dataset: 'sqlite', seeded: true, signal_count: 100 });
    expect(await screen.findByTestId('data-source-banner')).toHaveTextContent(/demo data/i);
  });

  it('renders nothing for the warehouse', async () => {
    renderWithHealth({ status: 'ok', dataset: 'warehouse', seeded: true, signal_count: 100 });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByTestId('data-source-banner')).not.toBeInTheDocument();
  });

  it('renders an unreachable warning', async () => {
    renderWithHealth(null);
    expect(await screen.findByTestId('data-source-banner')).toHaveTextContent(/unreachable/i);
  });
});

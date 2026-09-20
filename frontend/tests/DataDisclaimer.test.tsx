import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as apiClient from '../src/api/client';
import { DatasetProvider } from '../src/api/DatasetProvider';
import { DataDisclaimer } from '../src/components/DataDisclaimer';

vi.mock('../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return { ...actual, getHealth: vi.fn() };
});

function health(dataset: 'sqlite' | 'warehouse'): apiClient.Health {
  return { status: 'ok', dataset, seeded: true, signal_count: 10 };
}

beforeEach(() => vi.clearAllMocks());

describe('DataDisclaimer', () => {
  it('calls the demo dataset synthetic', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue(health('sqlite'));

    render(
      <DatasetProvider>
        <DataDisclaimer />
      </DatasetProvider>,
    );

    expect(await screen.findByTestId('data-disclaimer')).toHaveTextContent(
      /synthetic and fictitious/i,
    );
  });

  it('stops claiming real history is fictitious', async () => {
    // The bug this replaces: the footer asserted "synthetic and fictitious"
    // unconditionally while the badge beside it reported "Live history".
    vi.mocked(apiClient.getHealth).mockResolvedValue(health('warehouse'));

    render(
      <DatasetProvider>
        <DataDisclaimer />
      </DatasetProvider>,
    );

    const note = await screen.findByTestId('data-disclaimer');
    expect(note).not.toHaveTextContent(/synthetic/i);
    expect(note).toHaveTextContent(/real ingested history/i);
    // The warehouse serves unadjusted bars, and that stays disclosed.
    expect(note).toHaveTextContent(/unadjusted/i);
  });

  it('says so when the backend cannot be reached', async () => {
    vi.mocked(apiClient.getHealth).mockRejectedValue(new apiClient.ApiError(0, 'down'));

    render(
      <DatasetProvider>
        <DataDisclaimer />
      </DatasetProvider>,
    );

    expect(await screen.findByTestId('data-disclaimer')).toHaveTextContent(/unreachable/i);
  });

  it('asserts nothing at all until the backend has answered', () => {
    vi.mocked(apiClient.getHealth).mockReturnValue(new Promise(() => {}));

    const { container } = render(
      <DatasetProvider>
        <DataDisclaimer />
      </DatasetProvider>,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('reads the same health call as the badge rather than making its own', async () => {
    vi.mocked(apiClient.getHealth).mockResolvedValue(health('sqlite'));

    render(
      <DatasetProvider>
        <DataDisclaimer />
        <DataDisclaimer />
      </DatasetProvider>,
    );

    await screen.findAllByTestId('data-disclaimer');
    expect(apiClient.getHealth).toHaveBeenCalledTimes(1);
  });
});

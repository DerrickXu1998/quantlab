import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { UniversesProvider } from '../../src/api/UniversesProvider';
import type { Instrument } from '../../src/api/client';
import { UniversePicker } from '../../src/strategies/UniversePicker';

const instruments = [
  { symbol: 'AAPL.US', name: 'Apple', currency: 'USD' },
  { symbol: 'MSFT.US', name: 'Microsoft', currency: 'USD' },
] as unknown as Instrument[];

vi.mock('../../src/api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    listUniverses: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    createUniverse: vi.fn().mockResolvedValue({
      name: 'my-universe',
      as_of: '2026-09-27',
      size: 2,
    }),
  };
});

function Harness({ initial = [] as string[] }) {
  const [selected, setSelected] = useState(initial);
  return (
    <UniversesProvider>
      <UniversePicker instruments={instruments} selected={selected} onChange={setSelected} />
    </UniversesProvider>
  );
}

describe('UniversePicker save', () => {
  it('publishes the current selection as a named universe', async () => {
    const user = userEvent.setup();
    const { createUniverse } = await import('../../src/api/client');

    render(<Harness initial={['AAPL.US', 'MSFT.US']} />);

    const saveSection = screen.getByTestId('universe-save');
    await user.click(within(saveSection).getByRole('button', { name: /save as universe/i }));

    const input = within(saveSection).getByPlaceholderText(/universe name/i);
    await user.type(input, 'my-universe');
    await user.click(within(saveSection).getByRole('button', { name: /^save$/i }));

    expect(createUniverse).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'my-universe',
        symbols: ['AAPL.US', 'MSFT.US'],
      }),
    );
    expect(await within(saveSection).findByText(/saved "my-universe"/i)).toBeInTheDocument();
  });
});

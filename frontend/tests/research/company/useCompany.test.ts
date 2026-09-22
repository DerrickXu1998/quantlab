import { describe, expect, it } from 'vitest';
import { resolveInForce, todayISO } from '../../../src/research/company/useCompany';
import { makeFact } from './fixtures';

describe('resolveInForce', () => {
  it('trusts the server flag when the server sends one', () => {
    // The server resolves the point-in-time cut. Where it has already said
    // which row is in force, re-deriving it here would be a second
    // implementation of the rule the whole feature exists to have exactly one
    // of — and the second one is the one that drifts.
    const rows = resolveInForce([
      makeFact({
        concept: 'revenue',
        period_end: '2023-12-31',
        filed_at: '2024-02-14',
        in_force: false,
      }),
      makeFact({
        concept: 'revenue',
        period_end: '2022-12-31',
        filed_at: '2023-02-14',
        in_force: true,
      }),
    ]);

    expect(rows.filter((row) => row.inForce)).toHaveLength(1);
    expect(rows.find((row) => row.inForce)?.period_end).toBe('2022-12-31');
  });

  it('falls back to greatest period_end, then greatest filed_at', () => {
    const rows = resolveInForce([
      makeFact({ concept: 'revenue', period_end: '2022-12-31', filed_at: '2023-02-14' }),
      makeFact({ concept: 'revenue', period_end: '2023-12-31', filed_at: '2024-02-14' }),
      // A restatement of the same period, filed later: it wins the tie.
      makeFact({ concept: 'revenue', period_end: '2023-12-31', filed_at: '2024-08-01' }),
    ]);

    const chosen = rows.find((row) => row.inForce);
    expect(chosen?.period_end).toBe('2023-12-31');
    expect(chosen?.filed_at).toBe('2024-08-01');
    expect(rows.filter((row) => row.inForce)).toHaveLength(1);
  });

  it('decides each concept independently', () => {
    const rows = resolveInForce([
      makeFact({ concept: 'revenue', period_end: '2023-12-31', filed_at: '2024-02-14' }),
      makeFact({ concept: 'net_income', period_end: '2023-12-31', filed_at: '2024-02-14' }),
    ]);

    expect(
      rows
        .filter((row) => row.inForce)
        .map((row) => row.concept)
        .sort(),
    ).toEqual(['net_income', 'revenue']);
  });

  it('puts the in-force rows first, so the table reads as the current accounts', () => {
    const rows = resolveInForce([
      makeFact({ concept: 'revenue', period_end: '2022-12-31', filed_at: '2023-02-14' }),
      makeFact({ concept: 'revenue', period_end: '2023-12-31', filed_at: '2024-02-14' }),
      makeFact({ concept: 'cash', period_end: '2023-12-31', filed_at: '2024-02-14' }),
    ]);

    expect(rows.map((row) => row.inForce)).toEqual([true, true, false]);
    // Alphabetical within the in-force block.
    expect(rows.slice(0, 2).map((row) => row.concept)).toEqual(['cash', 'revenue']);
  });

  it('keeps every row, because a superseded filing is still a fact that was on file', () => {
    const facts = [
      makeFact({ concept: 'revenue', period_end: '2022-12-31', filed_at: '2023-02-14' }),
      makeFact({ concept: 'revenue', period_end: '2023-12-31', filed_at: '2024-02-14' }),
    ];
    expect(resolveInForce(facts)).toHaveLength(2);
  });

  it('is empty for no facts rather than inventing a row', () => {
    expect(resolveInForce([])).toEqual([]);
  });
});

describe('todayISO', () => {
  it('writes the local date the way a date input reads it', () => {
    expect(todayISO(new Date(2024, 5, 3))).toBe('2024-06-03');
  });
});

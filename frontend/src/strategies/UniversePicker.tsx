import { Plus, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { Instrument } from '../api/client';
import { Button } from '../components/ui/button';
import { fieldClasses } from '../components/ui/field';
import { StatusBadge } from '../components/ui/status-badge';
import { cn } from '../lib/utils';

/**
 * Macro series (FRED, Bank of England) are stored as pseudo-instruments so
 * they can be charted, but they have no tradable price -- a strategy "buying"
 * the Bank Rate is nonsense. They are left out of every preset and search.
 */
export function isTradable(instrument: Instrument): boolean {
  return !/\.(FRED|BOE)$/.test(instrument.symbol);
}

interface Preset {
  id: string;
  label: string;
  title: string;
  pick: (instrument: Instrument) => boolean;
}

const PRESETS: Preset[] = [
  {
    id: 'us',
    label: 'All US',
    title: 'Every US-listed ticker in the warehouse',
    pick: (instrument) => instrument.symbol.endsWith('.US'),
  },
  {
    id: 'uk',
    label: 'All UK',
    title: 'Every London-listed ticker in the warehouse',
    pick: (instrument) => instrument.symbol.endsWith('.LON'),
  },
  {
    id: 'all',
    label: 'Everything',
    title: 'Every tradable ticker, US and UK',
    pick: () => true,
  },
];

/** How many chips to draw before collapsing the rest behind "show all". */
const CHIP_LIMIT = 40;
const MATCH_LIMIT = 8;

/**
 * The tickers a strategy runs on.
 *
 * It replaces a five-row multi-select over 644 names: ctrl-clicking through a
 * list that shows two lines at a time is not a way to pick a universe. A
 * universe is usually a market (a preset) or a handful of names (search and
 * add), and either way you need to see what you picked.
 */
export function UniversePicker({
  instruments,
  selected,
  onChange,
}: {
  instruments: Instrument[];
  selected: string[];
  onChange: (symbols: string[]) => void;
}) {
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);

  const tradable = useMemo(() => instruments.filter(isTradable), [instruments]);
  const chosen = useMemo(() => new Set(selected), [selected]);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return [];
    return tradable
      .filter(
        (instrument) =>
          !chosen.has(instrument.symbol) &&
          (instrument.symbol.toLowerCase().includes(needle) ||
            instrument.name.toLowerCase().includes(needle)),
      )
      .sort((a, b) => {
        // A ticker that starts with what was typed beats one that merely contains it.
        const aStarts = a.symbol.toLowerCase().startsWith(needle) ? 0 : 1;
        const bStarts = b.symbol.toLowerCase().startsWith(needle) ? 0 : 1;
        return aStarts - bStarts || a.symbol.localeCompare(b.symbol);
      })
      .slice(0, MATCH_LIMIT);
  }, [query, tradable, chosen]);

  const add = (symbol: string) => {
    if (!chosen.has(symbol)) onChange([...selected, symbol]);
    setQuery('');
  };

  const remove = (symbol: string) => onChange(selected.filter((s) => s !== symbol));

  const applyPreset = (preset: Preset) =>
    onChange(tradable.filter(preset.pick).map((instrument) => instrument.symbol));

  const visible = showAll ? selected : selected.slice(0, CHIP_LIMIT);

  return (
    <div className="space-y-3" data-testid="universe-picker">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Universe presets">
        {PRESETS.map((preset) => {
          const count = tradable.filter(preset.pick).length;
          return (
            <Button
              key={preset.id}
              type="button"
              variant="outline"
              title={preset.title}
              disabled={count === 0}
              onClick={() => applyPreset(preset)}
            >
              {preset.label}
              <span className="text-muted-foreground">{count}</span>
            </Button>
          );
        })}
        <Button
          type="button"
          variant="ghost"
          disabled={selected.length === 0}
          onClick={() => onChange([])}
        >
          Clear
        </Button>
      </div>

      <div className="relative">
        <label htmlFor="universe-search" className="sr-only">
          Add tickers to the universe
        </label>
        <Search
          size={16}
          strokeWidth={1.5}
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
        />
        <input
          id="universe-search"
          type="search"
          autoComplete="off"
          placeholder="Add a ticker — type a symbol or name, Enter adds the first match"
          className={cn(fieldClasses, 'pl-9')}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && matches.length > 0) {
              event.preventDefault();
              add(matches[0].symbol);
            }
          }}
          aria-controls="universe-matches"
        />
        {matches.length > 0 ? (
          <ul
            id="universe-matches"
            aria-label="Matching tickers"
            className="absolute inset-x-0 top-full z-20 mt-1 max-h-72 overflow-y-auto border border-border bg-card"
          >
            {matches.map((instrument) => (
              <li key={instrument.symbol}>
                <button
                  type="button"
                  onClick={() => add(instrument.symbol)}
                  className="flex min-h-11 w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-accent/40 focus-visible:bg-accent/40 focus-visible:outline-none lg:min-h-9"
                >
                  <span className="font-mono text-sm text-foreground">{instrument.symbol}</span>
                  <span className="truncate text-sm text-muted-foreground">
                    {instrument.name !== instrument.symbol ? instrument.name : instrument.currency}
                  </span>
                  <Plus size={16} strokeWidth={1.5} aria-hidden="true" className="shrink-0" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div>
        <p className="mb-2 flex items-center gap-2 text-sm" data-testid="universe-count">
          <StatusBadge tone={selected.length > 0 ? 'active' : 'idle'}>
            {selected.length} {selected.length === 1 ? 'ticker' : 'tickers'}
          </StatusBadge>
          <span className="text-muted-foreground">
            {selected.length === 0
              ? 'Pick a preset or add tickers to run the strategy on.'
              : 'The strategy trades each of these independently, under the same rules.'}
          </span>
        </p>
        {selected.length > 0 ? (
          <ul aria-label="Selected tickers" className="flex flex-wrap gap-1.5">
            {visible.map((symbol) => (
              <li key={symbol}>
                <button
                  type="button"
                  onClick={() => remove(symbol)}
                  aria-label={`Remove ${symbol}`}
                  className="flex h-9 items-center gap-1 border border-border bg-card px-2 font-mono text-xs text-foreground transition-colors hover:border-destructive/60 lg:h-7"
                >
                  {symbol}
                  <X
                    size={16}
                    strokeWidth={1.5}
                    aria-hidden="true"
                    className="text-muted-foreground"
                  />
                </button>
              </li>
            ))}
            {selected.length > CHIP_LIMIT ? (
              <li>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowAll((value) => !value)}
                >
                  {showAll ? 'Show fewer' : `+${selected.length - CHIP_LIMIT} more — show all`}
                </Button>
              </li>
            ) : null}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

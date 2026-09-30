import { Bookmark, Plus, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { getUniverseMembers, type Instrument, type Universe } from '../api/client';
import { usePublishUniverse, useUniverses } from '../api/UniversesProvider';
import { Button } from '../components/ui/button';
import { Select, fieldClasses } from '../components/ui/field';
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

/**
 * One entry per saved universe: its newest snapshot. The list endpoint returns
 * every dated snapshot (newest first within a name), which is right for a
 * screen's as-of question and noise for "load the list I saved".
 */
export function latestSnapshots(universes: Universe[]): Universe[] {
  const newest = new Map<string, Universe>();
  for (const universe of universes) {
    const held = newest.get(universe.name);
    if (!held || universe.as_of > held.as_of) newest.set(universe.name, universe);
  }
  return [...newest.values()].sort((a, b) => a.name.localeCompare(b.name));
}

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
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const publish = usePublishUniverse();
  const { universes } = useUniverses();
  const saved = useMemo(() => latestSnapshots(universes), [universes]);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [loadNotice, setLoadNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(
    null,
  );

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

  // A saved universe replaces the selection, as a preset does. Members this
  // catalogue does not carry as tradable (a delisted name, a macro series) are
  // left out and counted, rather than sent to a run that would refuse them.
  const loadSaved = async (universe: Universe) => {
    setLoadingSaved(true);
    setLoadNotice(null);
    try {
      const members = await getUniverseMembers(universe.name, universe.as_of);
      const known = new Set(tradable.map((instrument) => instrument.symbol));
      const usable = members.symbols.filter((symbol) => known.has(symbol));
      const skipped = members.symbols.length - usable.length;
      onChange(usable);
      setLoadNotice({
        type: 'success',
        text:
          `Loaded "${universe.name}" as of ${members.as_of}: ${usable.length} tickers` +
          (skipped > 0 ? `, ${skipped} not in this catalogue left out.` : '.'),
      });
    } catch (caught: unknown) {
      setLoadNotice({
        type: 'error',
        text: caught instanceof Error ? caught.message : 'Could not load the universe.',
      });
    } finally {
      setLoadingSaved(false);
    }
  };

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

      {saved.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor="saved-universe"
            className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
          >
            Saved universes
          </label>
          <Select
            id="saved-universe"
            className="w-auto min-w-[14rem]"
            value=""
            disabled={loadingSaved}
            onChange={(event) => {
              const universe = saved.find((u) => u.name === event.target.value);
              if (universe) void loadSaved(universe);
            }}
          >
            <option value="">{loadingSaved ? 'Loading…' : 'Load a saved universe…'}</option>
            {saved.map((universe) => (
              <option key={universe.name} value={universe.name}>
                {universe.name} · {universe.size} · {universe.as_of}
              </option>
            ))}
          </Select>
          {loadNotice ? (
            <p
              data-testid="saved-universe-notice"
              className={cn(
                'basis-full text-xs',
                loadNotice.type === 'error' ? 'text-destructive' : 'text-primary',
              )}
              role={loadNotice.type === 'error' ? 'alert' : 'status'}
            >
              {loadNotice.text}
            </p>
          ) : null}
        </div>
      ) : null}

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

        {selected.length > 0 ? (
          <div className="space-y-2 border-t border-border pt-3" data-testid="universe-save">
            {!editing ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setEditing(true)}
              >
                <Bookmark size={16} strokeWidth={1.5} aria-hidden="true" className="mr-1.5" />
                Save as universe
              </Button>
            ) : (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
                <input
                  type="text"
                  autoComplete="off"
                  placeholder="Universe name"
                  className={cn(fieldClasses, 'h-8 text-sm')}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      void handleSave();
                    }
                    if (event.key === 'Escape') {
                      setEditing(false);
                      setNotice(null);
                    }
                  }}
                  disabled={saving}
                />
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    disabled={!name.trim() || saving}
                    onClick={() => void handleSave()}
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={saving}
                    onClick={() => {
                      setEditing(false);
                      setNotice(null);
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
            {notice ? (
              <p
                className={cn(
                  'text-xs',
                  notice.type === 'error' ? 'text-destructive' : 'text-primary',
                )}
                role={notice.type === 'error' ? 'alert' : 'status'}
              >
                {notice.text}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );

  async function handleSave() {
    const trimmed = name.trim();
    if (!trimmed || saving) return;
    setSaving(true);
    setNotice(null);
    try {
      await publish({
        name: trimmed,
        symbols: selected,
        snapshot_date: new Date().toISOString().slice(0, 10),
      });
      setNotice({ type: 'success', text: `Saved "${trimmed}" as a universe.` });
      setName('');
      setEditing(false);
    } catch (caught: unknown) {
      setNotice({
        type: 'error',
        text: caught instanceof Error ? caught.message : 'Could not save the universe.',
      });
    } finally {
      setSaving(false);
    }
  }
}

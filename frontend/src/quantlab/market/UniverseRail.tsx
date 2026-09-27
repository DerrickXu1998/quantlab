import { Check, Plus, Search, Trash2, X } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import type { Instrument } from '../../api/client';
import { Button } from '../../components/ui/button';
import { fieldClasses } from '../../components/ui/field';
import { cn } from '../../lib/utils';
import { MAX_TICKERS, parseTickers, resolveTickers } from './marketModel';
import type { CustomUniverse } from './useMarketData';

/** Rows drawn at once; a search narrows the rest. */
const ROW_LIMIT = 300;

interface UniverseOption {
  id: string;
  label: string;
  pick: (instrument: Instrument) => boolean;
  custom?: boolean;
}

const REGIME_LABEL: Record<string, string> = {
  trending: 'Trending',
  mean_reverting: 'Mean-reverting',
  volatile: 'Volatile',
  mixed: 'Mixed',
};

function builtIns(instruments: Instrument[]): UniverseOption[] {
  const options: UniverseOption[] = [{ id: 'all', label: 'All instruments', pick: () => true }];
  const has = (test: (i: Instrument) => boolean) => instruments.some(test);
  const us = (i: Instrument) => i.symbol.endsWith('.US');
  const uk = (i: Instrument) => i.symbol.endsWith('.LON');
  const macro = (i: Instrument) => /\.(FRED|BOE)$/.test(i.symbol);
  if (has(us)) options.push({ id: 'us', label: 'US listed', pick: us });
  if (has(uk)) options.push({ id: 'uk', label: 'UK listed', pick: uk });
  if (has(macro)) options.push({ id: 'macro', label: 'Macro series', pick: macro });
  for (const regime of Object.keys(REGIME_LABEL)) {
    const pick = (i: Instrument) => i.regime_profile === regime;
    if (has(pick)) options.push({ id: `regime:${regime}`, label: `Regime · ${REGIME_LABEL[regime]}`, pick });
  }
  return options;
}

const labelClass = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

export function UniverseRail({
  instruments,
  selected,
  onToggle,
  onSet,
  universes,
  onSaveUniverse,
  onDeleteUniverse,
}: {
  instruments: Instrument[];
  selected: string[];
  onToggle: (symbol: string) => void;
  onSet: (symbols: string[]) => void;
  universes: CustomUniverse[];
  onSaveUniverse: (universe: CustomUniverse) => void;
  onDeleteUniverse: (name: string) => void;
}) {
  const [universeId, setUniverseId] = useState('all');
  const [query, setQuery] = useState('');
  const [command, setCommand] = useState('');
  const [feedback, setFeedback] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState('');
  const [draftTickers, setDraftTickers] = useState('');
  const [draftError, setDraftError] = useState<string | null>(null);

  const known = useMemo(() => instruments.map((i) => i.symbol), [instruments]);
  const bySymbol = useMemo(() => new Map(instruments.map((i) => [i.symbol, i])), [instruments]);

  const options = useMemo<UniverseOption[]>(() => {
    const custom = universes.map((u) => {
      const members = new Set(u.symbols);
      return {
        id: `custom:${u.name}`,
        label: `${u.name} (${u.symbols.length})`,
        pick: (i: Instrument) => members.has(i.symbol),
        custom: true,
      };
    });
    return [...builtIns(instruments), ...custom];
  }, [instruments, universes]);

  const universe = options.find((o) => o.id === universeId) ?? options[0];

  const members = useMemo(() => instruments.filter(universe.pick), [instruments, universe]);
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return members;
    return members.filter(
      (i) => i.symbol.toLowerCase().includes(needle) || i.name.toLowerCase().includes(needle),
    );
  }, [members, query]);

  const full = selected.length >= MAX_TICKERS;

  // The terminal gesture: type tickers, press Enter (or GO), get charts.
  const submitCommand = (event: FormEvent) => {
    event.preventDefault();
    const typed = parseTickers(command);
    if (typed.length === 0) return;
    const { found, unknown } = resolveTickers(typed, known);
    const next = found.slice(0, MAX_TICKERS);
    const notes: string[] = [];
    if (unknown.length > 0) notes.push(`Not found: ${unknown.join(', ')}`);
    if (found.length > MAX_TICKERS) {
      notes.push(`Charting the first ${MAX_TICKERS}; dropped ${found.slice(MAX_TICKERS).join(', ')}`);
    }
    if (next.length > 0) {
      onSet(next);
      setCommand('');
    }
    setFeedback(notes.length > 0 ? notes.join('. ') : null);
  };

  const saveDraft = (event: FormEvent) => {
    event.preventDefault();
    const name = draftName.trim();
    const { found, unknown } = resolveTickers(parseTickers(draftTickers), known);
    if (!name) return setDraftError('Name the list.');
    if (found.length === 0) return setDraftError('Add at least one known ticker.');
    onSaveUniverse({ name, symbols: found });
    setUniverseId(`custom:${name}`);
    setEditing(false);
    setDraftName('');
    setDraftTickers('');
    setDraftError(null);
    setFeedback(unknown.length > 0 ? `Saved "${name}" without: ${unknown.join(', ')}` : null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-col gap-3 border-b border-border p-3">
        <form onSubmit={submitCommand} className="flex flex-col gap-1" aria-label="Chart tickers">
          <label htmlFor="market-command" className={labelClass}>
            Chart tickers
          </label>
          <div className="flex gap-1">
            <input
              id="market-command"
              data-testid="market-command"
              className={fieldClasses}
              value={command}
              placeholder="AAPL MSFT.US …"
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setCommand(event.target.value)}
            />
            <Button type="submit" size="sm" title="Chart these tickers (Enter)">
              GO
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            One to {MAX_TICKERS}, separated by spaces or commas. Replaces the current charts.
          </p>
          {feedback ? (
            <p role="status" data-testid="market-command-feedback" className="text-[11px] text-destructive">
              {feedback}
            </p>
          ) : null}
        </form>

        <div className="flex flex-col gap-1.5" data-testid="charted-tray">
          <div className="flex items-center justify-between">
            <span className={labelClass}>
              Charted{' '}
              <span data-testid="charted-count" className="text-foreground">
                {selected.length}/{MAX_TICKERS}
              </span>
            </span>
            {selected.length > 0 ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => onSet([])}>
                Clear
              </Button>
            ) : null}
          </div>
          {selected.length > 0 ? (
            <ul className="flex flex-wrap gap-1">
              {selected.map((symbol) => (
                <li key={symbol}>
                  <button
                    type="button"
                    onClick={() => onToggle(symbol)}
                    aria-label={`Remove ${symbol}`}
                    className="flex h-11 items-center gap-1 rounded-sm border border-primary/50 bg-primary/10 px-2 font-mono text-[11px] text-primary lg:h-7"
                  >
                    {symbol}
                    <X size={16} strokeWidth={1.5} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-muted-foreground">Nothing charted yet.</p>
          )}
          {selected.length > 1 ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setEditing(true);
                setDraftTickers(selected.join(' '));
              }}
            >
              <Plus size={16} strokeWidth={1.5} aria-hidden="true" />
              Save charted as a list
            </Button>
          ) : null}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="market-universe" className={labelClass}>
            Universe
          </label>
          <div className="flex gap-1">
            <select
              id="market-universe"
              data-testid="market-universe"
              className={fieldClasses}
              value={universe.id}
              onChange={(event) => setUniverseId(event.target.value)}
            >
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
            {universe.custom ? (
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label={`Delete list ${universe.label}`}
                title="Delete this list"
                onClick={() => {
                  onDeleteUniverse(universe.id.slice('custom:'.length));
                  setUniverseId('all');
                }}
              >
                <Trash2 size={16} strokeWidth={1.5} aria-hidden="true" />
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="New custom list"
              title="Build a custom universe"
              aria-expanded={editing}
              onClick={() => setEditing((open) => !open)}
            >
              <Plus size={16} strokeWidth={1.5} aria-hidden="true" />
            </Button>
          </div>
          {editing ? (
            <form
              onSubmit={saveDraft}
              aria-label="New custom list"
              className="mt-1 flex flex-col gap-1.5 border border-border p-2"
            >
              <input
                aria-label="List name"
                className={fieldClasses}
                placeholder="Name, e.g. Mega-cap tech"
                value={draftName}
                onChange={(event) => setDraftName(event.target.value)}
              />
              <textarea
                aria-label="Tickers"
                className={cn(fieldClasses, 'h-20 py-1 lg:h-20')}
                placeholder="Paste tickers: AAPL MSFT NVDA …"
                value={draftTickers}
                onChange={(event) => setDraftTickers(event.target.value)}
              />
              {draftError ? <p className="text-[11px] text-destructive">{draftError}</p> : null}
              <div className="flex gap-1">
                <Button type="submit" size="sm">
                  Save list
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Saved in this browser. Any size — you chart up to {MAX_TICKERS} of it at a time.
              </p>
            </form>
          ) : null}
        </div>

        <div className="relative">
          <Search
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            aria-label="Search instruments"
            data-testid="market-search"
            className={cn(fieldClasses, 'pl-8')}
            placeholder={`Search ${members.length.toLocaleString()} instruments`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto" data-testid="universe-list">
        {matches.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">No instruments match.</p>
        ) : (
          <ul className="divide-y divide-border">
            {matches.slice(0, ROW_LIMIT).map((instrument) => {
              const checked = selected.includes(instrument.symbol);
              const disabled = !checked && full;
              return (
                <li key={instrument.symbol}>
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={checked}
                    disabled={disabled}
                    title={disabled ? `Up to ${MAX_TICKERS} charts at once — remove one first` : instrument.name}
                    onClick={() => onToggle(instrument.symbol)}
                    className={cn(
                      'flex min-h-11 w-full items-center gap-2 border-l-2 px-3 py-1.5 text-left transition-colors lg:min-h-0',
                      checked ? 'border-l-primary bg-primary/5' : 'border-l-transparent hover:bg-accent/40',
                      disabled && 'cursor-not-allowed opacity-40 hover:bg-transparent',
                    )}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        'flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border',
                        checked ? 'border-primary bg-primary text-primary-foreground' : 'border-border',
                      )}
                    >
                      {checked ? <Check size={16} strokeWidth={1.5} className="h-3 w-3" /> : null}
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="font-mono text-[11px] tracking-[0.08em]">{instrument.symbol}</span>
                      {instrument.name && instrument.name !== instrument.symbol ? (
                        <span className="truncate text-xs text-muted-foreground">{instrument.name}</span>
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {matches.length > ROW_LIMIT ? (
          <p className="px-3 py-2 text-center text-[11px] text-muted-foreground">
            Showing {ROW_LIMIT} of {matches.length.toLocaleString()} — search to narrow.
          </p>
        ) : null}
      </div>
      <p className="shrink-0 border-t border-border px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
        {members.length.toLocaleString()} in universe · {bySymbol.size.toLocaleString()} total
      </p>
    </div>
  );
}

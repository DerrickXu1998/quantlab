import { Search, ServerCrash, X } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { Instrument } from '../../api/client';
import { fieldClasses } from '../../components/ui/field';
import { cn } from '../../lib/utils';
import type { ReadStatus } from './useCompany';

/**
 * How many matches are put in the DOM at once.
 *
 * 644 instruments is small for a filter and large for a list: rendering every
 * match on every keystroke is 644 mounted rows and a visibly janky first
 * character. Capping the *rendered* set — while still counting every match, and
 * saying so under the list — keeps the keystroke cheap without pretending the
 * rest of the catalogue is not there.
 */
export const RENDER_LIMIT = 50;

interface Ranked {
  instrument: Instrument;
  rank: number;
}

/**
 * Symbol first, then name — because that is the order a researcher types in.
 *
 * Someone who knows the ticker types the ticker and expects it at the top even
 * when a dozen company names contain the same three letters. Someone who only
 * remembers "Caterpillar" gets it from the name pass. Ranking rather than
 * filtering twice keeps both in one list, ordered by how well each matched.
 */
export function matchInstruments(instruments: Instrument[], query: string): Instrument[] {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return [...instruments].sort((a, b) => (a.symbol < b.symbol ? -1 : 1));
  }

  const ranked: Ranked[] = [];
  for (const instrument of instruments) {
    const symbol = instrument.symbol.toLowerCase();
    const name = (instrument.name ?? '').toLowerCase();
    let rank: number;
    if (symbol === needle) rank = 0;
    else if (symbol.startsWith(needle)) rank = 1;
    else if (name.startsWith(needle)) rank = 2;
    else if (symbol.includes(needle)) rank = 3;
    else if (name.includes(needle)) rank = 4;
    else continue;
    ranked.push({ instrument, rank });
  }

  return ranked
    .sort((a, b) =>
      a.rank !== b.rank ? a.rank - b.rank : a.instrument.symbol < b.instrument.symbol ? -1 : 1,
    )
    .map((entry) => entry.instrument);
}

export interface SymbolPickerProps {
  instruments: Instrument[];
  status: ReadStatus;
  message: string | null;
  selected: string | null;
  onSelect: (symbol: string) => void;
}

/**
 * The first action on the destination.
 *
 * There was previously no way to name a company at all — you reached one by
 * clicking a signal row that happened to mention it (docs/RESEARCH.md §1c). So
 * this control is the answer to "what do I do here", and it is deliberately the
 * widest thing on the screen and the only one that takes focus on arrival.
 */
export function SymbolPicker({
  instruments,
  status,
  message,
  selected,
  onSelect,
}: SymbolPickerProps) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);

  const matches = useMemo(() => matchInstruments(instruments, query), [instruments, query]);
  const shown = matches.slice(0, RENDER_LIMIT);
  const chosen = useMemo(
    () => instruments.find((instrument) => instrument.symbol === selected) ?? null,
    [instruments, selected],
  );

  useEffect(() => {
    setActive(0);
  }, [query]);

  // A click anywhere else is a dismissal. Without this the list stays open
  // behind the panels below it and intercepts the next click.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  function choose(instrument: Instrument) {
    onSelect(instrument.symbol);
    setQuery('');
    setOpen(false);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) setOpen(true);
      if (shown.length === 0) return;
      const step = event.key === 'ArrowDown' ? 1 : -1;
      setActive((current) => (current + step + shown.length) % shown.length);
      return;
    }
    if (event.key === 'Enter') {
      if (!open || shown.length === 0) return;
      event.preventDefault();
      choose(shown[active] ?? shown[0]);
    }
  }

  const disabled = status !== 'ready' || instruments.length === 0;

  return (
    <div ref={rootRef} className="relative min-w-0 flex-1">
      <label
        htmlFor={`${listId}-input`}
        className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
      >
        Company
      </label>
      <div className="relative mt-1">
        <Search
          size={16}
          strokeWidth={1.5}
          aria-hidden="true"
          className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
        />
        <input
          id={`${listId}-input`}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            open && shown[active] ? `${listId}-${shown[active].symbol}` : undefined
          }
          autoComplete="off"
          disabled={disabled}
          className={cn(fieldClasses, 'pl-8 pr-8 text-xs')}
          placeholder={placeholderFor(status, instruments.length, chosen)}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {selected && !query ? (
          <button
            type="button"
            aria-label={`Clear ${selected}`}
            title="Clear the selected company"
            onClick={() => {
              setQuery('');
              setOpen(true);
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
          >
            <X size={16} strokeWidth={1.5} />
          </button>
        ) : null}
      </div>

      <p className="mt-1 text-xs text-muted-foreground">
        {captionFor(status, message, chosen)}
      </p>

      {open && !disabled ? (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-80 overflow-y-auto rounded-sm border border-border bg-card">
          {shown.length === 0 ? (
            <p
              data-testid="symbol-picker-no-match"
              className="px-3 py-4 text-center text-xs text-muted-foreground"
            >
              No instrument matches “{query.trim()}”. The catalogue holds{' '}
              {instruments.length.toLocaleString('en-US')} names; this is not one of them.
            </p>
          ) : (
            <ul id={listId} role="listbox" aria-label="Instruments" className="py-1">
              {shown.map((instrument, index) => (
                <li
                  key={instrument.symbol}
                  id={`${listId}-${instrument.symbol}`}
                  role="option"
                  aria-selected={index === active}
                  onMouseEnter={() => setActive(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => choose(instrument)}
                  className={cn(
                    'flex cursor-pointer items-baseline gap-3 px-3 py-1.5 transition-colors',
                    index === active ? 'bg-accent text-accent-foreground' : 'text-foreground',
                  )}
                >
                  <span className="w-20 shrink-0 font-mono text-[11px] tabular-nums text-primary">
                    {instrument.symbol}
                  </span>
                  <span className="truncate text-xs">{instrument.name}</span>
                </li>
              ))}
            </ul>
          )}
          {matches.length > shown.length ? (
            <p className="border-t border-border px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              {shown.length} of {matches.length.toLocaleString('en-US')} matches — keep typing
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function placeholderFor(status: ReadStatus, total: number, chosen: Instrument | null): string {
  if (status === 'loading') return 'Loading the instrument catalogue…';
  if (status === 'unsupported') return 'The instrument catalogue is not served here';
  if (status === 'error') return 'The instrument catalogue could not be read';
  if (chosen) return `${chosen.symbol} — ${chosen.name}`;
  return `Search ${total.toLocaleString('en-US')} instruments by symbol or name`;
}

function captionFor(status: ReadStatus, message: string | null, chosen: Instrument | null): string {
  if (status === 'loading') return 'Reading the catalogue of instruments.';
  if (status === 'unsupported') {
    return 'This backend does not serve /instruments, so there is nothing to search.';
  }
  if (status === 'error') {
    return `The catalogue could not be read${message ? `: ${message}` : '.'}`;
  }
  if (chosen) return `Showing ${chosen.name}. Type to look up another.`;
  return 'Type a ticker or part of a company name, then press Enter.';
}

/**
 * The retry affordance for a catalogue that would not load.
 *
 * Separate from the picker so the picker stays one control: an input that
 * sometimes grows a button is harder to reason about than an input beside a
 * button that is sometimes there.
 */
export function SymbolPickerRetry({
  status,
  onRetry,
}: {
  status: ReadStatus;
  onRetry: () => void;
}) {
  if (status !== 'error') return null;
  return (
    <button
      type="button"
      onClick={onRetry}
      className="mt-5 inline-flex h-9 items-center gap-1.5 rounded-sm border border-border px-3 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:text-foreground"
    >
      <ServerCrash size={16} strokeWidth={1.5} />
      Retry
    </button>
  );
}

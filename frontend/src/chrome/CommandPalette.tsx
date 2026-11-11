import { Command } from 'cmdk';
import { ChartLine, CornerDownLeft, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { matchInstruments } from '../research/company/SymbolPicker';
import { useInstruments } from '../research/company/useCompany';
import { displaySymbol } from '../research/format';
import type { NavItem } from './MobileMenu';
import { navigate } from './router';

/** How many companies a query lists. The rest are one more keystroke away. */
const COMPANY_LIMIT = 8;

const ITEM =
  'flex cursor-pointer items-center gap-3 rounded-sm px-3 py-2 text-sm text-muted-foreground data-[selected=true]:bg-primary/10 data-[selected=true]:text-foreground';
const HEADING =
  '[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:type-label [&_[cmdk-group-heading]]:text-muted-foreground';

/**
 * One search for the whole app, on Cmd/Ctrl+K: type a ticker or a company
 * name and open it in Research or chart it in Market, or jump to a
 * destination. It reuses the Research picker's ranking, so the same query
 * finds the same company in both places.
 */
export function CommandPalette({
  open,
  onOpenChange,
  destinations,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  destinations: NavItem[];
}) {
  const [query, setQuery] = useState('');
  const instruments = useInstruments();

  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const companies = useMemo(
    () =>
      query.trim() === '' ? [] : matchInstruments(instruments.data, query).slice(0, COMPANY_LIMIT),
    [instruments.data, query],
  );
  const pages = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return destinations.filter((item) => item.label.toLowerCase().includes(needle));
  }, [destinations, query]);

  const run = (action: () => void) => {
    onOpenChange(false);
    action();
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Search companies and pages"
      shouldFilter={false}
      overlayClassName="fixed inset-0 z-40 bg-background/80"
      contentClassName="fixed left-1/2 top-[18vh] z-50 w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 rounded-sm border border-border bg-card"
    >
      <div className="flex items-center gap-3 border-b border-border px-3">
        <Search size={16} strokeWidth={1.5} aria-hidden="true" className="text-muted-foreground" />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search a ticker, a company or a page"
          className="h-12 w-full bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
      </div>

      <Command.List className="max-h-[50vh] overflow-y-auto p-1">
        <Command.Empty className="px-3 py-6 text-center text-sm text-muted-foreground">
          {instruments.status === 'loading' ? 'Loading companies…' : 'Nothing matches.'}
        </Command.Empty>

        {companies.length > 0 ? (
          <Command.Group heading="Open in Research" className={HEADING}>
            {companies.map((instrument) => (
              <Command.Item
                key={`research-${instrument.symbol}`}
                value={`research-${instrument.symbol}`}
                className={ITEM}
                onSelect={() => run(() => navigate('research', { symbol: instrument.symbol }))}
              >
                <span className="w-20 shrink-0 font-mono text-xs text-foreground">
                  {displaySymbol(instrument.symbol)}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {instrument.name === instrument.symbol ? '' : instrument.name}
                </span>
                <CornerDownLeft size={16} strokeWidth={1.5} aria-hidden="true" />
              </Command.Item>
            ))}
          </Command.Group>
        ) : null}

        {companies.length > 0 ? (
          <Command.Group heading="Chart in Market" className={HEADING}>
            {companies.slice(0, 3).map((instrument) => (
              <Command.Item
                key={`market-${instrument.symbol}`}
                value={`market-${instrument.symbol}`}
                className={ITEM}
                onSelect={() => run(() => navigate('market', { symbols: instrument.symbol }))}
              >
                <ChartLine size={16} strokeWidth={1.5} aria-hidden="true" />
                <span className="font-mono text-xs text-foreground">
                  {displaySymbol(instrument.symbol)}
                </span>
              </Command.Item>
            ))}
          </Command.Group>
        ) : null}

        {pages.length > 0 ? (
          <Command.Group heading="Go to" className={HEADING}>
            {pages.map((item) => (
              <Command.Item
                key={item.id}
                value={`page-${item.id}`}
                className={ITEM}
                onSelect={() => run(() => navigate(item.id))}
              >
                <item.icon size={16} strokeWidth={1.5} aria-hidden="true" />
                {item.label}
              </Command.Item>
            ))}
          </Command.Group>
        ) : null}
      </Command.List>
    </Command.Dialog>
  );
}

/** Cmd+K on a Mac, Ctrl+K elsewhere; toggles, so the same chord closes it. */
export function useCommandPaletteShortcut(toggle: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        toggle();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggle]);
}

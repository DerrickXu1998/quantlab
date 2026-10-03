import { BookOpen, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '../components/ui/button';
import { TERMS, type TermDefinition, type TermGroup } from './terms';
import { describeUnit } from './units';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';
const GROUPS: TermGroup[] = ['Results', 'Benchmark', 'Execution', 'Strategy', 'Data'];

/**
 * Every term QuantLab explains on hover, in one searchable list: the same
 * definitions the tooltips show, read from glossary/terms.ts.
 */
export function GlossaryButton() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <>
      <Button
        ref={trigger}
        type="button"
        variant="ghost"
        size="sm"
        aria-label="Glossary of terms"
        title="Glossary of terms"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="h-11 w-11 justify-center px-0 lg:h-7 lg:w-7"
      >
        <BookOpen size={20} strokeWidth={1.5} aria-hidden="true" className="shrink-0" />
      </Button>
      {open ? (
        <GlossaryDialog
          onClose={() => {
            setOpen(false);
            trigger.current?.focus();
          }}
        />
      ) : null}
    </>
  );
}

function GlossaryDialog({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('');
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    search.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const entries = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (Object.values(TERMS) as TermDefinition[]).filter(
      (entry) =>
        !needle ||
        entry.label.toLowerCase().includes(needle) ||
        entry.short.toLowerCase().includes(needle),
    );
  }, [query]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-background/80 px-4 py-8"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="glossary-title"
        data-testid="glossary"
        className="flex max-h-full w-full max-w-2xl flex-col rounded-sm border border-border bg-card"
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
          <h2 id="glossary-title" className={MICRO}>
            Glossary
          </h2>
          <input
            ref={search}
            type="search"
            aria-label="Search terms"
            placeholder="Search terms"
            className="h-8 min-w-0 flex-1 rounded-sm border border-border bg-background px-2 font-mono text-[11px] focus-visible:border-primary focus-visible:outline-none"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Close glossary"
            onClick={onClose}
          >
            <X size={16} strokeWidth={1.5} aria-hidden="true" />
          </Button>
        </header>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
          {entries.length === 0 ? (
            <p className="text-sm text-muted-foreground">No term matches “{query}”.</p>
          ) : (
            GROUPS.map((group) => {
              const items = entries.filter((entry) => entry.group === group);
              if (items.length === 0) return null;
              return (
                <section key={group} aria-label={group} className="space-y-2">
                  <h3 className={MICRO}>{group}</h3>
                  <dl className="divide-y divide-border border-y border-border">
                    {items.map((entry) => (
                      <div
                        key={entry.label}
                        className="grid gap-1 py-2 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4"
                      >
                        <dt className="font-mono text-[11px] uppercase tracking-[0.12em]">
                          {entry.label}
                        </dt>
                        <dd className="space-y-1 text-xs leading-relaxed">
                          <p>{entry.short}</p>
                          {entry.unit ? (
                            <p className="text-muted-foreground">
                              <span className={`${MICRO} mr-1`}>Unit</span>
                              {describeUnit(entry.unit, '1d')}
                            </p>
                          ) : null}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </section>
              );
            })
          )}
          <p className="text-xs text-muted-foreground">
            Signal-rule parameters (k_period, fast, oversold, …) explain themselves on hover, with
            the rule's own description and the unit at the bar size in use.
          </p>
        </div>
      </div>
    </div>
  );
}

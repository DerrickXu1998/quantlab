import { BookMarked, Hourglass, ServerCrash } from 'lucide-react';
import { useState } from 'react';
import type { CatalogModel, StrategyRole } from '../api/types';
import { ConfirmDelete } from '../components/ConfirmDelete';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { TabBar, tabId } from '../components/ui/tabs';
import { SignalCatalogue } from './SignalCatalogue';
import { StrategyStatusBadge, statusOf } from './StrategyStatus';
import type { useStrategyTemplates } from './templates';
import type { useStrategyLibrary } from './useStrategyLibrary';
import type { useFundamentalsCoverage } from './useFundamentals';

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';

export type LibraryList = 'mine' | 'templates' | 'signals';

/**
 * Two shelves: generic starters, and the presets replicating the AI-quant-book
 * plan. The book shelf says what those presets are for -- falsifiable
 * baselines, each predicting its own failure mode -- and repeats the
 * unadjusted-price caveat, because a long-horizon backtest of them is exactly
 * where a split gap turns into a fake signal.
 */
const TEMPLATE_SHELVES: { id: 'starter' | 'ai-quant-book'; label: string; note?: string }[] = [
  { id: 'starter', label: 'Starters' },
  {
    id: 'ai-quant-book',
    label: 'AI Quant Book presets',
    note: 'Regime-routed baselines from the strategy plan (S1, S2, S6, S7). Each description says where it should fail — a backtest that does not fail there is a bug signal. Splits and dividends are adjusted by default (Execution → Splits & dividends); a run made before that traded raw prices — check its trades on split dates.',
  },
];

type Library = ReturnType<typeof useStrategyLibrary>;
type Templates = ReturnType<typeof useStrategyTemplates>;
type Coverage = ReturnType<typeof useFundamentalsCoverage>['coverage'];

/**
 * Where strategies come from: your saved ones, ready-made templates, and the
 * signal catalogue. One list at a time behind a switcher, where it used to be
 * three stacked panels that pushed the strategy itself below the fold.
 */
export function LibraryRail({
  list,
  onListChange,
  library,
  templates,
  catalog,
  modelsLoading,
  coverage,
  currentId,
  runNames,
  onLoadStrategy,
  onLoadTemplate,
  onAdd,
  onDeleted,
}: {
  list: LibraryList;
  onListChange: (list: LibraryList) => void;
  library: Library;
  templates: Templates;
  catalog: CatalogModel[];
  modelsLoading: boolean;
  coverage: Coverage;
  currentId: string | null;
  runNames: ReadonlySet<string>;
  onLoadStrategy: (strategy: Library['items'][number]) => void;
  onLoadTemplate: (templateId: string) => void;
  onAdd: (model: CatalogModel, role: StrategyRole) => void;
  onDeleted: (strategyId: string) => void;
}) {
  return (
    <aside aria-label="Strategy library" className="flex min-h-0 flex-col gap-3" data-testid="library-rail">
      <TabBar<LibraryList>
        label="Library"
        idPrefix="library"
        value={list}
        onChange={onListChange}
        items={[
          { id: 'mine', label: 'Mine', badge: library.items.length, badgeLabel: `${library.items.length} saved` },
          { id: 'templates', label: 'Templates' },
          { id: 'signals', label: 'Signals' },
        ]}
      />
      <div
        role="tabpanel"
        id={`library-panel-${list}`}
        aria-labelledby={tabId('library', list)}
        className="min-h-0 flex-1 space-y-2 overflow-y-auto"
      >
        {list === 'mine' ? (
          <SavedStrategies
            library={library}
            currentId={currentId}
            runNames={runNames}
            onLoad={onLoadStrategy}
            onDeleted={onDeleted}
          />
        ) : list === 'templates' ? (
          <TemplateShelves templates={templates} onLoad={onLoadTemplate} />
        ) : modelsLoading ? (
          <EmptyState icon={Hourglass} title="Loading the registry…" role="status" />
        ) : (
          <SignalCatalogue catalog={catalog} coverage={coverage} onAdd={onAdd} />
        )}
      </div>
    </aside>
  );
}

function SavedStrategies({
  library,
  currentId,
  runNames,
  onLoad,
  onDeleted,
}: {
  library: Library;
  currentId: string | null;
  runNames: ReadonlySet<string>;
  onLoad: (strategy: Library['items'][number]) => void;
  onDeleted: (strategyId: string) => void;
}) {
  const [query, setQuery] = useState('');
  if (library.status === 'loading') {
    return <EmptyState icon={Hourglass} title="Loading…" role="status" />;
  }
  if (library.status === 'error') {
    return (
      <EmptyState
        testId="library-error"
        icon={ServerCrash}
        tone="error"
        title="Could not load your strategies"
        detail={library.error ?? undefined}
        action={
          <Button type="button" size="sm" variant="outline" onClick={library.reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (library.items.length === 0) {
    return (
      <EmptyState
        testId="library-empty"
        icon={BookMarked}
        title="Nothing saved yet"
        detail="Assemble a strategy — or load a template — and press Save. Saved strategies are private to your account."
      />
    );
  }
  const needle = query.trim().toLowerCase();
  const items = needle
    ? library.items.filter((strategy) => strategy.name.toLowerCase().includes(needle))
    : library.items;
  return (
    <>
      {library.items.length > 6 ? (
        <input
          type="search"
          aria-label="Search your strategies"
          placeholder="Search your strategies"
          className="h-8 w-full rounded-sm border border-border bg-card px-2 font-mono text-[11px] focus-visible:border-primary focus-visible:outline-none"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      ) : null}
      <ul className="divide-y divide-border" data-testid="strategy-library">
        {items.map((strategy) => (
          <li key={strategy.id} className="flex items-center gap-2 py-1.5">
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              aria-current={currentId === strategy.id ? 'true' : undefined}
              onClick={() => onLoad(strategy)}
            >
              <span className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-mono text-[11px]">{strategy.name}</span>
                <StrategyStatusBadge status={statusOf(strategy.name, runNames)} />
              </span>
              <span className="block text-xs text-muted-foreground">
                <span className="tabular-nums">{strategy.components.length}</span> components ·{' '}
                {strategy.entry_logic} in / {strategy.exit_logic} out
              </span>
            </button>
            <ConfirmDelete
              label={`Delete strategy ${strategy.name}`}
              title="Delete strategy"
              onConfirm={async () => {
                await library.remove(strategy.id);
                onDeleted(strategy.id);
              }}
            >
              Delete
            </ConfirmDelete>
          </li>
        ))}
      </ul>
    </>
  );
}

function TemplateShelves({ templates, onLoad }: { templates: Templates; onLoad: (id: string) => void }) {
  if (templates.status === 'loading') {
    return <EmptyState icon={Hourglass} title="Loading templates…" role="status" />;
  }
  if (templates.status === 'error') {
    return (
      <EmptyState
        testId="templates-error"
        icon={ServerCrash}
        tone="error"
        title="Could not load the templates"
        detail={templates.error ?? undefined}
        action={
          <Button type="button" size="sm" variant="outline" onClick={templates.reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (templates.items.length === 0) {
    return (
      <EmptyState
        testId="templates-empty"
        icon={BookMarked}
        title="No templates offered"
        detail="This backend serves no starter strategies. Build one from the Signals list instead."
      />
    );
  }
  return (
    <>
      <p className="text-xs text-muted-foreground">
        A worked strategy, loaded into the builder in one click. Nothing is saved until you press
        Save, so these are safe to open and take apart.
      </p>
      {TEMPLATE_SHELVES.map((shelf) => {
        const items = templates.items.filter(
          (template) => (template.collection ?? 'starter') === shelf.id,
        );
        if (items.length === 0) return null;
        return (
          <section
            key={shelf.id}
            aria-label={shelf.label}
            data-testid={`template-shelf-${shelf.id}`}
            className="space-y-2"
          >
            <div className="flex items-baseline justify-between gap-2">
              <h3 className={MICRO}>{shelf.label}</h3>
              <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                {items.length}
              </span>
            </div>
            {shelf.note ? <p className="text-xs text-muted-foreground">{shelf.note}</p> : null}
            <ul data-testid="template-list" className="space-y-2">
              {items.map((template) => (
                <li key={template.id} className="border border-border p-2">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-mono text-[11px]">{template.name}</p>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      aria-label={`Load the ${template.name} template`}
                      onClick={() => onLoad(template.id)}
                    >
                      Load
                    </Button>
                  </div>
                  {template.description ? (
                    <p className="mt-1 text-xs text-muted-foreground">{template.description}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );
}

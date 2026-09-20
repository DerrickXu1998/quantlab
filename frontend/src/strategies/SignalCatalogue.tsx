import { PackageOpen, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { CatalogModel, StrategyRole } from '../api/types';
import { CATEGORY_LABELS, ROLE_EXPLAINERS, ROLE_LABELS, STRATEGY_ROLES } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { Input } from '../components/ui/field';
import { StatusBadge } from '../components/ui/status-badge';
import { canFillRole, roleRefusal } from './strategyModel';

const MICRO = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

/**
 * One signal, everything the registry says about it, and the three roles it
 * could be given.
 *
 * A role a rule cannot fill is rendered as `aria-disabled` rather than
 * `disabled`: a disabled control cannot be focused and cannot be clicked, so
 * the one question the user has — *why not?* — has nowhere to be answered.
 * Here the button still takes focus and still responds; what it does is
 * explain itself.
 */
function SignalCard({
  model,
  onAdd,
}: {
  model: CatalogModel;
  onAdd: (model: CatalogModel, role: StrategyRole) => void;
}) {
  const [refusal, setRefusal] = useState<string | null>(null);

  return (
    <Card data-testid={`signal-card-${model.name}`} className="h-full">
      <CardHeader>
        <CardTitle className="truncate text-foreground">{model.name}</CardTitle>
        <span className="flex shrink-0 items-center gap-1.5">
          <StatusBadge tone="idle">{CATEGORY_LABELS[model.category]}</StatusBadge>
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            v{model.version}
          </span>
        </span>
      </CardHeader>

      <CardContent className="space-y-2">
        <p className="text-xs">{model.summary}</p>
        <p className="text-[11px] text-muted-foreground">{model.direction_semantics}</p>

        <p className={MICRO}>
          Parameters:{' '}
          <span className="normal-case tracking-normal text-foreground">
            {model.parameters.length === 0
              ? 'none'
              : model.parameters.map((spec) => spec.name).join(', ')}
          </span>
        </p>
        <p className={MICRO}>
          <span className="tabular-nums">{model.lookback_days}</span> bar warm-up
        </p>

        <div className="flex flex-wrap items-center gap-1.5 border-t border-border pt-2">
          <span className={MICRO}>Add as</span>
          {STRATEGY_ROLES.map((role) => {
            const allowed = canFillRole(model, role);
            return (
              <Button
                key={role}
                type="button"
                size="sm"
                variant={allowed ? 'outline' : 'ghost'}
                aria-disabled={allowed ? undefined : true}
                title={allowed ? ROLE_EXPLAINERS[role] : (roleRefusal(model, role) ?? undefined)}
                className={allowed ? undefined : 'text-muted-foreground/60'}
                onClick={() => {
                  if (!allowed) {
                    setRefusal(roleRefusal(model, role));
                    return;
                  }
                  setRefusal(null);
                  onAdd(model, role);
                }}
              >
                {ROLE_LABELS[role]}
              </Button>
            );
          })}
        </div>

        {refusal ? (
          <p
            role="alert"
            data-testid={`role-refusal-${model.name}`}
            className="border border-destructive/40 bg-destructive/5 px-2 py-1 text-[11px] text-destructive"
          >
            {refusal}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * The whole registry, grouped by what a signal is *for* rather than
 * alphabetically.
 *
 * Category comes off the wire (§2). Grouping by it is what lets someone who
 * knows they want "something that fades an overextended move" find the mean
 * reversion rules without already knowing their names.
 */
export function SignalCatalogue({
  catalog,
  onAdd,
}: {
  catalog: CatalogModel[];
  onAdd: (model: CatalogModel, role: StrategyRole) => void;
}) {
  const [query, setQuery] = useState('');

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matching = catalog.filter(
      (model) =>
        needle === '' ||
        model.name.toLowerCase().includes(needle) ||
        model.summary.toLowerCase().includes(needle) ||
        CATEGORY_LABELS[model.category].toLowerCase().includes(needle),
    );
    const byCategory = new Map<CatalogModel['category'], CatalogModel[]>();
    for (const model of matching) {
      const bucket = byCategory.get(model.category) ?? [];
      bucket.push(model);
      byCategory.set(model.category, bucket);
    }
    return [...byCategory.entries()].sort(([a], [b]) =>
      CATEGORY_LABELS[a].localeCompare(CATEGORY_LABELS[b]),
    );
  }, [catalog, query]);

  if (catalog.length === 0) {
    return (
      <EmptyState
        testId="catalogue-empty"
        icon={PackageOpen}
        title="No signals registered"
        detail="The registry is empty. Register a signal rule in the backend and it appears here without a frontend change."
      />
    );
  }

  return (
    <div className="space-y-4" data-testid="signal-catalogue">
      <div className="flex items-center gap-2">
        <Search size={16} strokeWidth={1.5} aria-hidden="true" className="text-muted-foreground" />
        <Input
          type="search"
          aria-label="Filter signals"
          placeholder="Filter by name, category or what it does"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {groups.length === 0 ? (
        <EmptyState
          testId="catalogue-no-match"
          icon={Search}
          title="Nothing matches that"
          detail={`No registered signal matches "${query.trim()}". Clear the filter to see all ${catalog.length}.`}
        />
      ) : (
        groups.map(([category, models]) => (
          <section key={category} aria-label={CATEGORY_LABELS[category]} className="space-y-2">
            <h3 className={MICRO}>
              {CATEGORY_LABELS[category]}
              <span className="ml-2 tabular-nums">{models.length}</span>
            </h3>
            <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
              {models.map((model) => (
                <SignalCard key={`${model.name}@${model.version}`} model={model} onAdd={onAdd} />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

import { PackageOpen, SearchX } from 'lucide-react';
import { useMemo } from 'react';
import type { CatalogModel } from '../../api/types';
import { CATEGORY_LABELS, ROLE_EXPLAINERS, ROLE_LABELS, SIGNAL_CATEGORIES } from '../../api/types';
import { EmptyState } from '../../components/ui/empty-state';
import { fieldClasses } from '../../components/ui/field';
import { StatusBadge } from '../../components/ui/status-badge';
import { conceptLabel, formatCount } from '../format';

/**
 * The rule catalogue — every rule, not the three with history.
 *
 * The panel this replaces was the signals table, which showed the output of
 * whichever rules had been materialised into `signals`. That was three of
 * twenty-two (docs/RESEARCH.md §1b), so the destination silently advertised
 * three rules and hid nineteen, including every rule that reads filed
 * accounts. This list comes from the registry instead, so a rule appears
 * because it exists, not because a batch job once ran it.
 *
 * It is also called Rules rather than Models, because that is what they are:
 * predicates over a price or accounting series, with no weights and nothing
 * fitted. "Model" invites "trained on what?", which has no answer.
 */
export interface RuleCatalogueProps {
  rules: CatalogModel[];
  /** How many runs this workspace has recorded per rule name. */
  runsByRule: Map<string, number>;
  selected: string | null;
  onSelect: (name: string) => void;
  query: string;
  onQuery: (value: string) => void;
}

function categoryOrder(category: string): number {
  const index = (SIGNAL_CATEGORIES as readonly string[]).indexOf(category);
  return index === -1 ? SIGNAL_CATEGORIES.length : index;
}

function categoryLabel(category: string): string {
  return (
    CATEGORY_LABELS[category as keyof typeof CATEGORY_LABELS] ??
    category.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
  );
}

function matches(rule: CatalogModel, needle: string): boolean {
  if (needle === '') return true;
  const haystack = [
    rule.name,
    rule.summary,
    rule.category,
    ...(rule.requires_facts ?? []).map(conceptLabel),
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle);
}

export function RuleCatalogue({
  rules,
  runsByRule,
  selected,
  onSelect,
  query,
  onQuery,
}: RuleCatalogueProps) {
  const needle = query.trim().toLowerCase();

  const groups = useMemo(() => {
    const byCategory = new Map<string, CatalogModel[]>();
    for (const rule of rules) {
      if (!matches(rule, needle)) continue;
      const bucket = byCategory.get(rule.category) ?? [];
      bucket.push(rule);
      byCategory.set(rule.category, bucket);
    }
    return [...byCategory.entries()]
      .map(([category, items]) => ({
        category,
        items: [...items].sort((a, b) => a.name.localeCompare(b.name)),
      }))
      .sort((a, b) => categoryOrder(a.category) - categoryOrder(b.category));
  }, [rules, needle]);

  const shown = groups.reduce((total, group) => total + group.items.length, 0);
  const neverRun = rules.filter((rule) => (runsByRule.get(rule.name) ?? 0) === 0).length;

  if (rules.length === 0) {
    return (
      <EmptyState
        testId="rule-catalogue-empty"
        icon={PackageOpen}
        title="No rules registered"
        detail="The registry is empty. Register a rule in the backend and it appears here with no frontend change."
      />
    );
  }

  return (
    <div className="space-y-3" data-testid="rule-catalogue">
      <p className="text-[11px] leading-snug text-muted-foreground" data-testid="rule-census">
        {formatCount(rules.length)} rules in the registry, every one of them listed.{' '}
        {neverRun > 0
          ? `${formatCount(neverRun)} have never been run here — a rule with no history is untried, not broken.`
          : 'Each has been run at least once here.'}
      </p>

      <input
        type="search"
        aria-label="Filter rules"
        placeholder="Filter by name, concept or category"
        className={fieldClasses}
        value={query}
        onChange={(event) => onQuery(event.target.value)}
      />

      {shown === 0 ? (
        <EmptyState
          testId="rule-catalogue-no-match"
          icon={SearchX}
          title="No rule matches that"
          detail={`All ${formatCount(rules.length)} rules are still here — clear the filter to see them.`}
        />
      ) : (
        <div className="space-y-4">
          {groups.map((group) => (
            <section key={group.category} data-testid={`rule-group-${group.category}`}>
              <h3 className="mb-1.5 flex items-baseline justify-between gap-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                {categoryLabel(group.category)}
                <span className="tabular-nums">{group.items.length}</span>
              </h3>
              <ul className="divide-y divide-border border-y border-border">
                {group.items.map((rule) => (
                  <li key={`${rule.name}@${rule.version}`}>
                    <RuleRow
                      rule={rule}
                      runs={runsByRule.get(rule.name) ?? 0}
                      active={rule.name === selected}
                      onSelect={() => onSelect(rule.name)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function RuleRow({
  rule,
  runs,
  active,
  onSelect,
}: {
  rule: CatalogModel;
  runs: number;
  active: boolean;
  onSelect: () => void;
}) {
  // The exact optional-chain that crashed this app once: `requires_facts` is
  // absent on a backend that predates §2, and `model?.requires_facts.length`
  // throws on the *property*, not on the model. The normaliser fills it in,
  // and this guards it again at the point of use.
  const concepts = rule.requires_facts ?? [];
  const roles = rule.roles ?? [];

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? 'true' : undefined}
      data-testid={`rule-${rule.name}`}
      className={`w-full border-l-2 px-3 py-2.5 text-left transition-colors ${
        active ? 'border-l-primary bg-primary/5' : 'border-l-transparent hover:bg-accent/40'
      }`}
    >
      <span className="flex items-baseline justify-between gap-2">
        <span className="truncate font-mono text-[12px] text-foreground">{rule.name}</span>
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
          v{rule.version}
        </span>
      </span>

      {/* The registry has always carried this line; the old panel discarded it. */}
      <span className="mt-1 block text-[11px] leading-snug text-muted-foreground">
        {rule.summary}
      </span>

      <span className="mt-1.5 flex flex-wrap items-center gap-1">
        {roles.map((role) => (
          <StatusBadge key={role} tone="idle" title={ROLE_EXPLAINERS[role]}>
            {ROLE_LABELS[role]}
          </StatusBadge>
        ))}
        {runs === 0 ? (
          <StatusBadge
            tone="disabled"
            testId={`rule-untried-${rule.name}`}
            title="Nothing in this workspace has run this rule yet. It is registered and runnable."
          >
            No runs yet
          </StatusBadge>
        ) : (
          <StatusBadge tone="good" title="Runs recorded in this workspace">
            {formatCount(runs)} {runs === 1 ? 'run' : 'runs'}
          </StatusBadge>
        )}
      </span>

      <span className="mt-1.5 block font-mono text-[10px] tabular-nums text-muted-foreground">
        {formatCount(rule.lookback_days)}d lookback · {rule.scale_class.replace('_', '-')}
      </span>

      {concepts.length > 0 ? (
        <span
          className="mt-1.5 block text-[10px] leading-snug text-muted-foreground"
          data-testid={`rule-concepts-${rule.name}`}
        >
          <span className="font-mono uppercase tracking-[0.12em]">Reads</span>{' '}
          {concepts.map(conceptLabel).join(', ')}
        </span>
      ) : (
        <span className="mt-1.5 block text-[10px] leading-snug text-muted-foreground">
          <span className="font-mono uppercase tracking-[0.12em]">Reads</span> price bars only
        </span>
      )}
    </button>
  );
}

import { PackageOpen, Pencil, Trash2 } from 'lucide-react';
import { useState } from 'react';
import type { CustomRule } from '../quantlab/data/customRules';
import type { ModelEntry } from '../runs/RunsContext';
import { describeRule } from '../workbench/templateSpec';
import { Button } from './ui/button';
import { EmptyState } from './ui/empty-state';
import { Numeric } from './ui/numeric';
import { StatusBadge } from './ui/status-badge';

const NO_EXECUTION = 'No execution backend — QuantLab computes signals, it does not place orders.';

function ModeChips() {
  return (
    <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <StatusBadge tone="active">Simulated</StatusBadge>
      <StatusBadge tone="disabled" title={NO_EXECUTION}>
        Paper
      </StatusBadge>
      <StatusBadge tone="disabled" title={NO_EXECUTION}>
        Live
      </StatusBadge>
    </span>
  );
}

function EntryMeta({ entry }: { entry: ModelEntry }) {
  const { model, runs, latest } = entry;
  return (
    <span className="mt-1.5 flex flex-wrap items-center gap-x-3 text-[10px] text-muted-foreground">
      <span className="font-mono">
        <Numeric value={model.lookback_days} format="integer" className="text-[10px]" />d lookback
      </span>
      <span className="font-mono">{model.scale_class.replace('_', '-')}</span>
      <span className="font-mono">
        <Numeric value={runs.length} format="integer" className="text-[10px]" />{' '}
        {runs.length === 1 ? 'run' : 'runs'}
      </span>
      {latest ? (
        <span className="flex items-center gap-1">
          last
          <Numeric value={latest.signal_count} format="integer" className="text-[10px]" />
          sig
        </span>
      ) : null}
    </span>
  );
}

const rowClasses = (active: boolean) =>
  `w-full border-l-2 px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-primary ${
    active ? 'border-l-primary bg-primary/5' : 'border-l-transparent hover:bg-accent/40'
  }`;

/**
 * A custom rule's row: the selection button plus rename/delete affordances.
 * Delete is a two-step row action — there is no undo against the backend,
 * though the rule's runs keep their snapshot either way.
 */
function CustomRuleRow({
  entry,
  rule,
  selected,
  onSelect,
  onEdit,
  onDelete,
}: {
  entry: ModelEntry;
  rule: CustomRule | undefined;
  selected: boolean;
  onSelect: () => void;
  onEdit?: (rule: CustomRule) => void;
  onDelete?: (rule: CustomRule) => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { model } = entry;
  const active = selected;

  return (
    <li className="group relative">
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? 'true' : undefined}
        className={rowClasses(active)}
      >
        <span className="flex items-baseline justify-between gap-2 pr-12">
          <span className="truncate font-mono text-[12px]">{model.name}</span>
          <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
            {model.template}
          </span>
        </span>

        <span
          data-testid={`fires-on-${model.name}`}
          className="mt-1 block text-[11px] text-muted-foreground"
        >
          {/* The summary is generated from the rule's own config — the same
              sentence the builder previews, never stored copy. */}
          {rule ? describeRule(rule.template, rule.config) : (model.template ?? 'Custom rule')}
        </span>

        <ModeChips />
        <EntryMeta entry={entry} />
      </button>

      {error ? (
        <span role="alert" className="block px-3 py-1 text-[10px] text-destructive">
          {error}
        </span>
      ) : null}

      {rule && (onEdit || onDelete) ? (
        <span className="absolute right-2 top-2 flex items-center gap-1">
          {confirming ? (
            <>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={deleting}
                className="border-destructive/50 text-destructive hover:text-destructive"
                onClick={async () => {
                  if (!onDelete) return;
                  setDeleting(true);
                  setError(null);
                  try {
                    await onDelete(rule);
                    setConfirming(false);
                  } catch (caught: unknown) {
                    setError(
                      caught instanceof Error ? caught.message : 'could not delete the rule',
                    );
                  } finally {
                    setDeleting(false);
                  }
                }}
              >
                {deleting ? 'Deleting…' : 'Confirm'}
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                Keep
              </Button>
            </>
          ) : (
            <>
              {onEdit ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  aria-label={`Edit rule ${rule.name}`}
                  title="Edit this rule"
                  onClick={() => onEdit(rule)}
                >
                  <Pencil size={16} strokeWidth={1.5} aria-hidden="true" />
                </Button>
              ) : null}
              {onDelete ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  aria-label={`Delete rule ${rule.name}`}
                  title="Delete this rule"
                  onClick={() => setConfirming(true)}
                >
                  <Trash2 size={16} strokeWidth={1.5} aria-hidden="true" />
                </Button>
              ) : null}
            </>
          )}
        </span>
      ) : null}
    </li>
  );
}

export interface RuleActions {
  onEdit: (rule: CustomRule) => void;
  onDelete: (rule: CustomRule) => Promise<void>;
}

/**
 * The strategy list, used by both Research and Strategies, grouped into
 * builtins and the caller's own rules.
 *
 * Every entry comes from the backend registry at request time — nothing about
 * model identity is hardcoded here, which is what makes registering a model
 * (or saving a custom rule) enough to make it appear (Constitution II). The
 * one-line "fires on" description is composed from the registry's own
 * `direction_semantics` for builtins and generated from each custom rule's
 * config, never from per-model copy kept in the frontend.
 *
 * The SIM/PAPER/LIVE chips a terminal usually carries are not faked here.
 * Simulation is the only mode the backend has, so it is the only one lit; the
 * other two are rendered visibly disabled with the reason on hover. Showing a
 * lit LIVE badge over a system that cannot trade would be the single most
 * misleading thing on the screen.
 */
export function ModelList({
  entries,
  selected,
  onSelect,
  rules,
  ruleActions,
}: {
  entries: ModelEntry[];
  selected: string | null;
  onSelect: (name: string) => void;
  /** The caller's custom rules; passing them enables the "My rules" group. */
  rules?: CustomRule[];
  /** Edit/delete affordances on custom rows; absent in read-only contexts. */
  ruleActions?: RuleActions;
}) {
  if (entries.length === 0) {
    return (
      <EmptyState
        testId="model-list-empty"
        icon={PackageOpen}
        title="No models registered"
        detail="The model registry is empty. Register a signal rule in the backend and it appears here without a frontend change."
      />
    );
  }

  const builtin = entries.filter((entry) => entry.model.origin !== 'custom');
  const custom = entries.filter((entry) => entry.model.origin === 'custom');
  const ruleById = new Map((rules ?? []).map((rule) => [rule.rule_id, rule]));
  // Management contexts keep the group visible even while empty, so the
  // affordance has a stable home.
  const showCustomGroup = custom.length > 0 || rules !== undefined;

  return (
    <ul data-testid="model-list">
      {builtin.length > 0 ? (
        <li data-testid="model-group-builtin">
          <h3 className="border-b border-border px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            Builtin
            <span className="ml-2 text-muted-foreground/60">{builtin.length}</span>
          </h3>
          <ul className="divide-y divide-border">
            {builtin.map((entry) => {
              const { model } = entry;
              const active = model.name === selected;
              return (
                <li key={`${model.name}@${model.version}`}>
                  <button
                    type="button"
                    onClick={() => onSelect(model.name)}
                    aria-current={active ? 'true' : undefined}
                    className={rowClasses(active)}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate font-mono text-[12px]">{model.name}</span>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                        v{model.version}
                      </span>
                    </span>

                    <span
                      data-testid={`fires-on-${model.name}`}
                      className="mt-1 block text-[11px] text-muted-foreground"
                    >
                      Fires {model.direction_semantics}
                    </span>

                    <ModeChips />
                    <EntryMeta entry={entry} />
                  </button>
                </li>
              );
            })}
          </ul>
        </li>
      ) : null}

      {showCustomGroup ? (
        <li data-testid="model-group-custom">
          <h3 className="border-b border-border px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            My rules
            <span className="ml-2 text-muted-foreground/60">{custom.length}</span>
          </h3>
          {custom.length === 0 ? (
            <p className="px-3 py-3 text-[11px] text-muted-foreground">
              No custom rules yet — build one from a template and it runs like a builtin.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {custom.map((entry) => {
                const rule = ruleById.get(entry.model.custom_rule_id ?? '');
                return (
                  <CustomRuleRow
                    key={`${entry.model.name}@${entry.model.version}`}
                    entry={entry}
                    rule={rule}
                    selected={entry.model.name === selected}
                    onSelect={() => onSelect(entry.model.name)}
                    onEdit={ruleActions?.onEdit}
                    onDelete={ruleActions?.onDelete}
                  />
                );
              })}
            </ul>
          )}
        </li>
      ) : null}
    </ul>
  );
}

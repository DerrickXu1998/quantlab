import { Trash2, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import type { CatalogModel, StrategyRole } from '../api/types';
import { ROLE_EXPLAINERS, ROLE_LABELS, STRATEGY_ROLES } from '../api/types';
import { Button } from '../components/ui/button';
import { Input, Select } from '../components/ui/field';
import { StatusBadge } from '../components/ui/status-badge';
import { canFillRole, componentErrors, describeComponent, roleRefusal } from './strategyModel';
import type { DraftComponent } from './strategyModel';

const MICRO = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

const ROLE_TONE: Record<StrategyRole, 'active' | 'good' | 'idle'> = {
  entry: 'active',
  exit: 'good',
  filter: 'idle',
};

/**
 * One component of the strategy, editable in place.
 *
 * The parameter fields are generated from the rule's declared metadata and
 * validated through `paramSpec`, the same helpers the single-model run form
 * uses — two validators would eventually disagree, and the one that drifted
 * would accept a value the other rejected.
 */
export function StrategyComponentEditor({
  component,
  model,
  /** True when the strategy's logic for this component's side is `weighted`. */
  weighted,
  onChange,
  onRemove,
}: {
  component: DraftComponent;
  model: CatalogModel | null;
  weighted: boolean;
  onChange: (next: DraftComponent) => void;
  onRemove: () => void;
}) {
  const [refusal, setRefusal] = useState<string | null>(null);
  const errors = componentErrors(component, model);

  const setValue = (name: string, raw: string) =>
    onChange({ ...component, values: { ...component.values, [name]: raw } });

  return (
    <li
      data-testid={`component-${component.rule_name}-${component.role}`}
      className="space-y-2 border border-border bg-card p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-[12px]">{component.rule_name}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {describeComponent(component, model)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <StatusBadge tone={ROLE_TONE[component.role]} title={ROLE_EXPLAINERS[component.role]}>
            {ROLE_LABELS[component.role]}
          </StatusBadge>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={`Remove ${component.rule_name} from the strategy`}
            onClick={onRemove}
          >
            <Trash2 size={16} strokeWidth={1.5} aria-hidden="true" />
          </Button>
        </div>
      </div>

      {model === null ? (
        <p role="alert" className="flex gap-2 text-[11px] text-destructive">
          <TriangleAlert size={16} strokeWidth={1.5} className="shrink-0" aria-hidden="true" />
          <span>
            {component.rule_name} is not in the registry any more. The strategy stays readable, but
            it will not run until this component is removed or the rule is registered again.
          </span>
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <label className={MICRO}>
              Role
              <Select
                className="mt-1"
                value={component.role}
                aria-label={`Role for ${component.rule_name}`}
                onChange={(event) => {
                  const role = event.target.value as StrategyRole;
                  if (!canFillRole(model, role)) {
                    // The select is never silently reverted: the refusal says
                    // what the rule can do instead.
                    setRefusal(roleRefusal(model, role));
                    return;
                  }
                  setRefusal(null);
                  onChange({ ...component, role });
                }}
              >
                {STRATEGY_ROLES.map((role) => (
                  <option key={role} value={role} disabled={!canFillRole(model, role)}>
                    {ROLE_LABELS[role]}
                    {canFillRole(model, role) ? '' : ' — not supported'}
                  </option>
                ))}
              </Select>
            </label>

            {/* Weight is only read by weighted logic; showing it otherwise
                invites tuning a number that has no effect on the run. */}
            {weighted ? (
              <label className={MICRO}>
                Weight
                <Input
                  className="mt-1"
                  type="number"
                  step="any"
                  min={0}
                  data-testid={`weight-${component.id}`}
                  value={String(component.weight)}
                  aria-label={`Weight for ${component.rule_name}`}
                  onChange={(event) =>
                    onChange({ ...component, weight: Number(event.target.value) })
                  }
                />
              </label>
            ) : null}
          </div>

          {refusal ? (
            <p role="alert" className="text-[11px] text-destructive">
              {refusal}
            </p>
          ) : null}

          <div className="grid grid-cols-2 gap-2">
            {model.parameters.map((spec) => {
              const error = errors[spec.name];
              const errorId = `${component.id}-${spec.name}-error`;
              return (
                <label key={spec.name} className={MICRO}>
                  <span className="normal-case tracking-normal" title={spec.description}>
                    <span className="font-mono uppercase tracking-[0.12em]">{spec.name}</span>
                  </span>
                  {spec.type === 'enum' ? (
                    <Select
                      className="mt-1"
                      aria-label={`${spec.name} for ${component.rule_name}`}
                      value={component.values[spec.name] ?? ''}
                      onChange={(event) => setValue(spec.name, event.target.value)}
                    >
                      {(spec.choices ?? []).map((choice) => (
                        <option key={String(choice)} value={String(choice)}>
                          {String(choice)}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Input
                      className="mt-1"
                      aria-label={`${spec.name} for ${component.rule_name}`}
                      aria-invalid={error ? true : undefined}
                      aria-describedby={error ? errorId : undefined}
                      type={spec.type === 'int' || spec.type === 'float' ? 'number' : 'text'}
                      step={spec.type === 'float' ? 'any' : '1'}
                      min={spec.minimum ?? undefined}
                      max={spec.maximum ?? undefined}
                      value={component.values[spec.name] ?? ''}
                      onChange={(event) => setValue(spec.name, event.target.value)}
                    />
                  )}
                  {error ? (
                    <span id={errorId} role="alert" className="mt-1 block text-destructive">
                      {spec.name}: {error}
                    </span>
                  ) : null}
                </label>
              );
            })}
          </div>

          <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              checked={component.invert}
              onChange={(event) => onChange({ ...component, invert: event.target.checked })}
              className="h-3.5 w-3.5 rounded-sm border-input accent-primary"
            />
            Invert — read this component’s bullish and bearish the other way round.
          </label>
        </>
      )}
    </li>
  );
}

import { Trash2, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import type { CatalogModel, FundamentalsCoverage, StrategyRole } from '../api/types';
import { ROLE_EXPLAINERS, ROLE_LABELS, STRATEGY_ROLES, UNIT_PRESENTATION, unitOf } from '../api/types';
import { Button } from '../components/ui/button';
import { Input, Select } from '../components/ui/field';
import { StatusBadge } from '../components/ui/status-badge';
import { displayBound, displayValue, wireValue } from '../workbench/paramSpec';
import { conceptCoverage, conceptLabel } from './fundamentals';
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
  /** Warehouse coverage, for the concepts a fundamental rule reads (§5.2). */
  coverage = null,
  onChange,
  onRemove,
}: {
  component: DraftComponent;
  model: CatalogModel | null;
  weighted: boolean;
  coverage?: FundamentalsCoverage | null;
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
              // The declared unit, or nothing. A unit is never inferred from a
              // parameter's name: guessing that `min_margin` is a fraction and
              // silently dividing what was typed by 100 is a worse failure
              // than an unlabelled box.
              const unit = unitOf(spec);
              const presentation = unit === null ? null : UNIT_PRESENTATION[unit];
              const raw = component.values[spec.name] ?? '';
              return (
                <label key={spec.name} className={MICRO}>
                  <span className="normal-case tracking-normal" title={spec.description}>
                    <span className="font-mono uppercase tracking-[0.12em]">{spec.name}</span>
                  </span>
                  {spec.type === 'enum' ? (
                    <Select
                      className="mt-1"
                      aria-label={`${spec.name} for ${component.rule_name}`}
                      value={raw}
                      onChange={(event) => setValue(spec.name, event.target.value)}
                    >
                      {(spec.choices ?? []).map((choice) => (
                        <option key={String(choice)} value={String(choice)}>
                          {String(choice)}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <span className="mt-1 flex items-center gap-1.5">
                      <Input
                        aria-label={`${spec.name} for ${component.rule_name}`}
                        aria-invalid={error ? true : undefined}
                        aria-describedby={error ? errorId : undefined}
                        type={spec.type === 'int' || spec.type === 'float' ? 'number' : 'text'}
                        step={spec.type === 'float' ? 'any' : '1'}
                        min={displayBound(spec, spec.minimum)}
                        max={displayBound(spec, spec.maximum)}
                        // Displayed in the declared unit, held in the draft as
                        // the wire value — the same trick the execution form
                        // plays with stops and targets.
                        value={displayValue(spec, raw)}
                        onChange={(event) => setValue(spec.name, wireValue(spec, event.target.value))}
                      />
                      {presentation && presentation.suffix ? (
                        <span className="shrink-0">{presentation.suffix}</span>
                      ) : null}
                    </span>
                  )}
                  {presentation ? (
                    <span
                      data-testid={`unit-${component.id}-${spec.name}`}
                      className="mt-1 block normal-case tracking-normal text-muted-foreground"
                    >
                      {presentation.help}
                    </span>
                  ) : null}
                  {error ? (
                    <span id={errorId} role="alert" className="mt-1 block text-destructive">
                      {spec.name}: {error}
                    </span>
                  ) : null}
                </label>
              );
            })}
          </div>

          {/* What this rule reads, and what the warehouse actually holds of
              it. §5.2: the coverage window is read from the data rather than
              written down here — the FINRA short-volume concepts have one
              month of history, and a filter using them over an earlier window
              matches nothing at all. */}
          {model.requires_facts.length > 0 ? (
            <div
              data-testid={`requires-facts-${component.rule_name}`}
              className="space-y-1 border-t border-border pt-2"
            >
              <p className={MICRO}>Reads filed facts</p>
              <ul className="space-y-0.5">
                {model.requires_facts.map((concept) => {
                  const entry = conceptCoverage(coverage, concept);
                  return (
                    <li
                      key={concept}
                      className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-muted-foreground"
                    >
                      <span className="font-mono text-foreground">{conceptLabel(concept)}</span>
                      {entry ? (
                        <span className="font-mono tabular-nums">
                          {entry.instruments} instruments · {entry.first_filed} → {entry.last_filed}
                        </span>
                      ) : (
                        <span>coverage not reported for this concept</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

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

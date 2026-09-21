import { useEffect, useMemo, useRef, useState } from 'react';
import { getPrices, type Instrument, type Model, type RunRequest } from '../api/client';
import {
  buildExecutionCriteria,
  executionDefaults,
  executionError,
  visibleExecutionFields,
} from '../workbench/executionSpec';
import { coerce, defaultValues, localError } from '../workbench/paramSpec';
import { Button } from './ui/button';
import { fieldClasses, Input, Label, Select } from './ui/field';
import { StatusBadge } from './ui/status-badge';

/** Used when the data extent cannot be read: the demo dataset's window. */
const FALLBACK_WINDOW = { start: '2024-01-01', end: '2024-12-31' };

const NO_PREFILL: Record<string, string> = {};

/**
 * The one run-configuration form, shared by Research and Strategies.
 *
 * Generated from the model's declared parameter metadata — nothing about any
 * model is hardcoded (Constitution II) — and validated through paramSpec so
 * both destinations agree on what is valid.
 *
 * The date window defaults to the actual extent of the stored data (one price
 * read against the first instrument) rather than a hardcoded year. Below the
 * signal parameters, the Execution fieldset sets the criteria the run's
 * performance report simulates under — capital, sizing, costs, stops and fill
 * timing — which the backend records with the run and discloses in the
 * assumptions it ships back.
 */
export function RunConfigForm({
  model,
  instruments,
  running,
  onRun,
  onCancel,
  initialValues = NO_PREFILL,
}: {
  model: Model;
  instruments: Instrument[];
  running: boolean;
  onRun: (body: RunRequest) => void;
  onCancel?: () => void;
  /** Handoff prefill: parameter values as strings, keyed by parameter name. */
  initialValues?: Record<string, string>;
}) {
  const [values, setValues] = useState<Record<string, string>>(() => ({
    ...defaultValues(model.parameters),
    ...initialValues,
  }));
  // Execution criteria are model-independent, so they survive a model switch.
  const [execution, setExecution] = useState<Record<string, string>>(executionDefaults);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [startDate, setStartDate] = useState(FALLBACK_WINDOW.start);
  const [endDate, setEndDate] = useState(FALLBACK_WINDOW.end);
  // The extent backfill must not steamroll edits the researcher already made.
  const datesTouched = useRef(false);

  useEffect(() => {
    setValues({ ...defaultValues(model.parameters), ...initialValues });
  }, [model, initialValues]);

  useEffect(() => {
    const first = instruments[0]?.symbol;
    if (!first) return;
    let cancelled = false;
    getPrices(first)
      .then((bars) => {
        if (cancelled || datesTouched.current || bars.items.length === 0) return;
        const firstBar = bars.items[0];
        const lastBar = bars.items[bars.items.length - 1];
        setStartDate(firstBar.date);
        setEndDate(lastBar.date);
      })
      .catch(() => {
        // The fallback window stays; a missing extent is not an error here.
      });
    return () => {
      cancelled = true;
    };
  }, [instruments]);

  const fieldErrors = useMemo(() => {
    const errors: Record<string, string> = {};
    for (const spec of model.parameters) {
      const problem = localError(spec, values[spec.name] ?? '');
      if (problem) errors[spec.name] = problem;
    }
    return errors;
  }, [model, values]);

  const executionErrors = useMemo(() => {
    const errors: Record<string, string> = {};
    for (const spec of visibleExecutionFields(execution)) {
      const problem = executionError(spec, execution[spec.name] ?? '');
      if (problem) errors[spec.name] = problem;
    }
    return errors;
  }, [execution]);

  const blocked =
    Object.keys(fieldErrors).length > 0 ||
    Object.keys(executionErrors).length > 0 ||
    symbols.length === 0 ||
    running;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (blocked) return;
    const criteria = buildExecutionCriteria(execution);
    // A custom rule's config is fixed at definition time: the run names the
    // rule and carries no parameter overrides (the API rejects both at once).
    if (model.origin === 'custom' && model.custom_rule_id) {
      onRun({
        custom_rule_id: model.custom_rule_id,
        symbols,
        start_date: startDate,
        end_date: endDate,
        execution: criteria,
      });
      return;
    }
    // Only overrides are sent; omitted parameters take the declared default,
    // which is what keeps a run reproducible from its record.
    const overrides: Record<string, unknown> = {};
    for (const spec of model.parameters) {
      const raw = values[spec.name];
      if (raw !== undefined && raw !== String(spec.default)) {
        overrides[spec.name] = coerce(spec, raw);
      }
    }
    onRun({
      model_name: model.name,
      model_version: model.version,
      parameters: overrides,
      symbols,
      start_date: startDate,
      end_date: endDate,
      execution: criteria,
    });
  };

  const label = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

  return (
    <form onSubmit={submit} className="space-y-4" data-testid="run-config">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className={label} htmlFor="run-start">
            Start
          </label>
          <input
            id="run-start"
            type="date"
            className={fieldClasses}
            value={startDate}
            onChange={(event) => {
              datesTouched.current = true;
              setStartDate(event.target.value);
            }}
          />
        </div>
        <div className="space-y-1">
          <label className={label} htmlFor="run-end">
            End
          </label>
          <input
            id="run-end"
            type="date"
            className={fieldClasses}
            value={endDate}
            onChange={(event) => {
              datesTouched.current = true;
              setEndDate(event.target.value);
            }}
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className={label} htmlFor="run-symbols">
          Instruments
        </label>
        <select
          id="run-symbols"
          multiple
          size={5}
          className={`${fieldClasses} h-auto`}
          value={symbols}
          onChange={(event) =>
            setSymbols(Array.from(event.target.selectedOptions, (option) => option.value))
          }
        >
          {instruments.map((instrument) => (
            <option key={instrument.symbol} value={instrument.symbol}>
              {instrument.symbol} — {instrument.name}
            </option>
          ))}
        </select>
        <p className="text-[10px] text-muted-foreground">
          {symbols.length === 0 ? 'Select at least one.' : `${symbols.length} selected`}
        </p>
      </div>

      {model.parameters.length > 0 ? (
        <fieldset className="space-y-2 border-t border-border pt-3">
          <legend className={label}>Parameters</legend>
          {model.parameters.map((spec) => {
            const error = fieldErrors[spec.name];
            const describedBy = error ? `run-param-${spec.name}-error` : undefined;
            return (
              <div key={spec.name} className="space-y-1">
                <Label>
                  <span>
                    <span className="font-mono">{spec.name}</span>
                    {spec.description ? (
                      <span className="ml-2 font-sans text-[10px] normal-case tracking-normal text-muted-foreground">
                        {spec.description}
                      </span>
                    ) : null}
                  </span>
                  {spec.type === 'enum' ? (
                    <Select
                      value={values[spec.name] ?? ''}
                      aria-describedby={describedBy}
                      aria-invalid={Boolean(error)}
                      onChange={(event) =>
                        setValues((current) => ({ ...current, [spec.name]: event.target.value }))
                      }
                    >
                      {(spec.choices ?? []).map((choice) => (
                        <option key={String(choice)} value={String(choice)}>
                          {String(choice)}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Input
                      id={`run-param-${spec.name}`}
                      value={values[spec.name] ?? ''}
                      aria-describedby={describedBy}
                      aria-invalid={Boolean(error)}
                      min={spec.minimum ?? undefined}
                      max={spec.maximum ?? undefined}
                      type={spec.type === 'int' || spec.type === 'float' ? 'number' : 'text'}
                      step={spec.type === 'float' ? 'any' : '1'}
                      onChange={(event) =>
                        setValues((current) => ({ ...current, [spec.name]: event.target.value }))
                      }
                    />
                  )}
                </Label>
                {error ? (
                  <p
                    id={`run-param-${spec.name}-error`}
                    role="alert"
                    className="text-[10px] text-destructive"
                  >
                    {spec.name}: {error}
                  </p>
                ) : null}
              </div>
            );
          })}
        </fieldset>
      ) : model.origin === 'custom' ? (
        <p className="border-t border-border pt-3 text-[10px] text-muted-foreground">
          This rule's parameters are baked into its saved config — edit the rule to change them.
        </p>
      ) : null}

      <fieldset className="space-y-2 border-t border-border pt-3" data-testid="execution-fieldset">
        <legend className={label}>Execution</legend>
        <p className="text-[10px] text-muted-foreground">
          How the run’s performance report turns signals into simulated fills. Recorded with the
          run.
        </p>
        <div className="grid grid-cols-2 gap-3">
          {visibleExecutionFields(execution).map((spec) => {
            const error = executionErrors[spec.name];
            const id = `run-exec-${spec.name}`;
            const describedBy = error ? `${id}-error` : undefined;
            const control =
              spec.kind === 'enum' ? (
                <Select
                  id={id}
                  value={execution[spec.name] ?? ''}
                  aria-describedby={describedBy}
                  aria-invalid={Boolean(error)}
                  onChange={(event) =>
                    setExecution((current) => ({ ...current, [spec.name]: event.target.value }))
                  }
                >
                  {(spec.choices ?? []).map((choice) => (
                    <option key={choice.value} value={choice.value}>
                      {choice.label}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  id={id}
                  value={execution[spec.name] ?? ''}
                  aria-describedby={describedBy}
                  aria-invalid={Boolean(error)}
                  min={spec.minimum ?? undefined}
                  max={spec.maximum ?? undefined}
                  type="number"
                  step={spec.kind === 'float' ? 'any' : '1'}
                  onChange={(event) =>
                    setExecution((current) => ({ ...current, [spec.name]: event.target.value }))
                  }
                />
              );
            return (
              <div key={spec.name} className="space-y-1">
                <Label htmlFor={id}>
                  <span>
                    {spec.label}
                    <span className="ml-2 font-sans text-[10px] normal-case tracking-normal text-muted-foreground">
                      {spec.help}
                    </span>
                  </span>
                  {control}
                </Label>
                {error ? (
                  <p id={`${id}-error`} role="alert" className="text-[10px] text-destructive">
                    {spec.label}: {error}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      </fieldset>

      <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
        <StatusBadge tone="idle" title="The backend serves daily bars only.">
          Daily
        </StatusBadge>
        <span className="flex items-center gap-2">
          {running && onCancel ? (
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
          ) : null}
          <Button type="submit" disabled={blocked} className="px-4">
            {running ? 'Running…' : 'Run strategy'}
          </Button>
        </span>
      </div>

      {running ? (
        <p role="status" className="text-[11px] text-muted-foreground">
          Running the model over the selected dataset…
        </p>
      ) : null}
    </form>
  );
}

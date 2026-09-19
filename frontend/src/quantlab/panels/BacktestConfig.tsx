import { useEffect, useMemo, useState } from 'react';
import type { Instrument, Model, RunRequest } from '../../api/client';
import { defaultValues, localError, overridesFrom } from '../../workbench/paramSpec';
import { StatusBadge } from '../chrome/StatusBadge';

/**
 * The backtest form, generated from the model's declared parameter metadata.
 *
 * Reuses workbench/paramSpec so this form and the Signal Viewer's agree on
 * what is valid. Nothing about any model is hardcoded (Constitution II).
 *
 * Capital and timeframe are deliberately absent: the backend marks a fixed
 * notional book and serves daily bars only, so a field offering a choice it
 * cannot honour would be a lie in the shape of a control.
 */
export function BacktestConfig({
  model,
  instruments,
  running,
  onRun,
}: {
  model: Model;
  instruments: Instrument[];
  running: boolean;
  onRun: (body: RunRequest) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    defaultValues(model.parameters),
  );
  const [symbols, setSymbols] = useState<string[]>([]);
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-12-31');

  useEffect(() => {
    setValues(defaultValues(model.parameters));
  }, [model]);

  const fieldErrors = useMemo(() => {
    const errors: Record<string, string> = {};
    for (const spec of model.parameters) {
      const problem = localError(spec, values[spec.name] ?? '');
      if (problem) errors[spec.name] = problem;
    }
    return errors;
  }, [model, values]);

  const blocked = Object.keys(fieldErrors).length > 0 || symbols.length === 0 || running;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (blocked) return;
    onRun({
      model_name: model.name,
      model_version: model.version,
      parameters: overridesFrom(model.parameters, values),
      symbols,
      start_date: startDate,
      end_date: endDate,
    });
  };

  const field =
    'w-full rounded-sm border border-input bg-background px-2 py-1 font-mono text-[11px] text-foreground outline-none focus:border-primary';
  const label = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className={label} htmlFor="lab-start">
            Start
          </label>
          <input
            id="lab-start"
            type="date"
            className={field}
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label className={label} htmlFor="lab-end">
            End
          </label>
          <input
            id="lab-end"
            type="date"
            className={field}
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className={label} htmlFor="lab-symbols">
          Instruments
        </label>
        <select
          id="lab-symbols"
          multiple
          size={5}
          className={`${field} h-auto`}
          value={symbols}
          onChange={(event) =>
            setSymbols(Array.from(event.target.selectedOptions, (option) => option.value))
          }
        >
          {instruments.map((instrument) => (
            <option key={instrument.symbol} value={instrument.symbol}>
              {instrument.symbol}
            </option>
          ))}
        </select>
        <p className="text-[10px] text-muted-foreground">
          {symbols.length === 0 ? 'Select at least one.' : `${symbols.length} selected`}
        </p>
      </div>

      <div className="space-y-2 border-t border-border pt-3">
        <p className={label}>Parameters</p>
        {model.parameters.map((spec) => {
          const error = fieldErrors[spec.name];
          return (
            <div key={spec.name} className="space-y-1">
              <label className="block text-[11px]" htmlFor={`lab-param-${spec.name}`}>
                <span className="font-mono">{spec.name}</span>
                {spec.description ? (
                  <span className="ml-2 text-[10px] text-muted-foreground">
                    {spec.description}
                  </span>
                ) : null}
              </label>
              <input
                id={`lab-param-${spec.name}`}
                className={field}
                value={values[spec.name] ?? ''}
                aria-invalid={error ? 'true' : undefined}
                min={spec.minimum ?? undefined}
                max={spec.maximum ?? undefined}
                type={spec.type === 'int' || spec.type === 'float' ? 'number' : 'text'}
                step={spec.type === 'float' ? 'any' : undefined}
                onChange={(event) =>
                  setValues((current) => ({ ...current, [spec.name]: event.target.value }))
                }
              />
              {error ? (
                <p role="alert" className="text-[10px] text-destructive">
                  {spec.name} {error}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
        <StatusBadge tone="idle" title="The backend serves daily bars only.">
          Daily
        </StatusBadge>
        <button
          type="submit"
          disabled={blocked}
          className="rounded-sm border border-primary bg-primary px-4 py-1.5 font-mono text-[11px] uppercase tracking-wider text-primary-foreground disabled:cursor-not-allowed disabled:border-border disabled:bg-transparent disabled:text-muted-foreground"
        >
          {running ? 'Running…' : 'Run backtest'}
        </button>
      </div>
    </form>
  );
}

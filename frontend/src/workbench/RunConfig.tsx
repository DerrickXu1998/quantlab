import { useEffect, useMemo, useState } from 'react';
import { Button } from '../components/ui/button';
import { Input, Label, Select } from '../components/ui/field';
import { useWorkspace } from '../workspace/WorkspaceContext';
import { useWorkbench } from './WorkbenchContext';
// Shared with the Quant Lab backtest form: two copies of this would drift.
import { coerce, defaultValues, localError } from './paramSpec';

export function RunConfig() {
  const { selected, runs } = useWorkbench();
  const { instruments } = useWorkspace();
  const [values, setValues] = useState<Record<string, string>>({});
  const [symbols, setSymbols] = useState<string[]>([]);
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-12-31');

  // Seed the form from the selected model's declared defaults. Nothing about
  // parameter names or types is hardcoded — a model with parameters nobody
  // anticipated still renders a usable form.
  useEffect(() => {
    if (!selected) return;
    setValues(defaultValues(selected.parameters));
  }, [selected]);

  const fieldErrors = useMemo(() => {
    if (!selected) return {};
    const errors: Record<string, string> = {};
    for (const spec of selected.parameters) {
      const problem = localError(spec, values[spec.name] ?? '');
      if (problem) errors[spec.name] = problem;
    }
    return errors;
  }, [selected, values]);

  if (!selected) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        Select a model to configure a run.
      </div>
    );
  }

  const blocked = Object.keys(fieldErrors).length > 0 || symbols.length === 0;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (blocked) return;
    // Only overrides are sent; omitted parameters take the declared default.
    const overrides: Record<string, unknown> = {};
    for (const spec of selected.parameters) {
      const raw = values[spec.name];
      if (raw !== undefined && raw !== String(spec.default)) {
        overrides[spec.name] = coerce(spec, raw);
      }
    }
    void runs.start({
      model_name: selected.name,
      model_version: selected.version,
      parameters: overrides,
      symbols,
      start_date: startDate,
      end_date: endDate,
    });
  };

  return (
    <form className="h-full overflow-auto p-3" onSubmit={submit} data-testid="run-config">
      <h3 className="mb-3 text-sm font-semibold">
        {selected.name} <span className="text-muted-foreground">v{selected.version}</span>
      </h3>

      <fieldset className="mb-4 flex flex-col gap-3">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Parameters
        </legend>
        {selected.parameters.map((spec) => {
          const error = fieldErrors[spec.name];
          const describedBy = error ? `${spec.name}-error` : undefined;
          return (
            <Label key={spec.name}>
              {spec.name}
              {spec.type === 'enum' ? (
                <Select
                  value={values[spec.name] ?? ''}
                  aria-describedby={describedBy}
                  aria-invalid={Boolean(error)}
                  onChange={(e) => setValues((v) => ({ ...v, [spec.name]: e.target.value }))}
                >
                  {(spec.choices ?? []).map((choice) => (
                    <option key={String(choice)} value={String(choice)}>
                      {String(choice)}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  type={spec.type === 'bool' ? 'text' : 'number'}
                  step={spec.type === 'float' ? 'any' : '1'}
                  min={spec.minimum ?? undefined}
                  max={spec.maximum ?? undefined}
                  value={values[spec.name] ?? ''}
                  aria-describedby={describedBy}
                  aria-invalid={Boolean(error)}
                  onChange={(e) => setValues((v) => ({ ...v, [spec.name]: e.target.value }))}
                />
              )}
              {spec.description && (
                <span className="text-[11px] font-normal text-muted-foreground">
                  {spec.description}
                </span>
              )}
              {error && (
                <span
                  id={`${spec.name}-error`}
                  role="alert"
                  className="text-[11px] text-destructive"
                >
                  {spec.name}: {error}
                </span>
              )}
            </Label>
          );
        })}
      </fieldset>

      <fieldset className="mb-4 flex flex-col gap-3">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Dataset
        </legend>
        <Label>
          Instruments
          <select
            multiple
            size={5}
            value={symbols}
            aria-label="Instruments"
            className="rounded-md border border-input bg-card p-1 text-sm"
            onChange={(e) =>
              setSymbols(Array.from(e.target.selectedOptions, (option) => option.value))
            }
          >
            {instruments.map((instrument) => (
              <option key={instrument.symbol} value={instrument.symbol}>
                {instrument.symbol}
              </option>
            ))}
          </select>
        </Label>
        <Label>
          Start date
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </Label>
        <Label>
          End date
          <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </Label>
      </fieldset>

      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={blocked || runs.inFlight}>
          {runs.inFlight ? 'Running…' : 'Run'}
        </Button>
        {runs.inFlight && (
          <Button type="button" size="sm" variant="outline" onClick={runs.cancel}>
            Cancel
          </Button>
        )}
      </div>

      {runs.inFlight && (
        <p role="status" className="mt-2 text-xs text-muted-foreground">
          Running the model over the selected dataset…
        </p>
      )}
      {runs.error && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {runs.error}
        </p>
      )}
    </form>
  );
}

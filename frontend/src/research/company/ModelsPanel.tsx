import { Eye, EyeOff, Hourglass, Play, Sigma, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { CatalogModel, ParamSpecV2 } from '../../api/types';
import { CATEGORY_LABELS, UNIT_PRESENTATION, unitOf } from '../../api/types';
import { Button } from '../../components/ui/button';
import { Label, Select, fieldClasses } from '../../components/ui/field';
import { StatusBadge } from '../../components/ui/status-badge';
import { cn } from '../../lib/utils';
import {
  coerce,
  defaultValues,
  displayBound,
  displayValue,
  localError,
  wireValue,
} from '../../workbench/paramSpec';
import { formatCount, formatPercent } from '../format';
import { Panel } from './Panel';
import { markerLabel, type ModelOverlay } from './useModelOverlays';

/**
 * Models that say *when*: the ones with an entry or exit role. Filters are
 * gates that read true or false on every bar -- an arrow under every candle
 * says nothing -- and they earn their keep combined with a signal, which is
 * what the Strategies builder is for.
 */
export function signalModels(catalog: CatalogModel[]): CatalogModel[] {
  return catalog.filter((model) => model.roles.some((role) => role !== 'filter'));
}

const DEFAULT_MODEL = 'sma-crossover';

function paramSummary(parameters: Record<string, unknown>): string {
  const entries = Object.entries(parameters);
  return entries.length === 0
    ? 'defaults'
    : entries.map(([name, value]) => `${name}=${String(value)}`).join(', ');
}

/** The strategy's return against simply holding the name over the same window. */
function Outcome({ overlay }: { overlay: ModelOverlay }) {
  const performance = overlay.performance;
  if (!performance) return null;
  const { metrics, benchmark, initial_capital: capital } = performance;
  const held = benchmark.length > 0 ? benchmark[benchmark.length - 1].value / capital - 1 : null;
  return (
    <p className="font-mono text-xs tabular-nums text-muted-foreground">
      {formatCount(overlay.signals.length)} signals · {formatCount(metrics.trade_count)} trades ·{' '}
      <span className={metrics.total_return >= 0 ? 'text-primary' : 'text-destructive'}>
        {metrics.total_return >= 0 ? '+' : ''}
        {formatPercent(metrics.total_return)}
      </span>{' '}
      vs hold {held === null ? '—' : `${held >= 0 ? '+' : ''}${formatPercent(held)}`}
    </p>
  );
}

function OverlayRow({
  overlay,
  onToggle,
  onRemove,
}: {
  overlay: ModelOverlay;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const name = overlay.model.name;
  return (
    <li
      data-testid="model-overlay"
      className={cn(
        'flex items-start gap-2 border-b border-border px-3 py-2.5 last:border-b-0',
        !overlay.visible && 'opacity-60',
      )}
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-pressed={overlay.visible}
        aria-label={overlay.visible ? `Hide ${name} on the chart` : `Show ${name} on the chart`}
        disabled={overlay.status !== 'ready'}
        onClick={onToggle}
        className="shrink-0"
      >
        {overlay.visible ? (
          <Eye size={16} strokeWidth={1.5} aria-hidden="true" />
        ) : (
          <EyeOff size={16} strokeWidth={1.5} aria-hidden="true" />
        )}
      </Button>
      <div className="min-w-0 flex-1 space-y-1 pt-1 lg:pt-0.5">
        <p className="flex flex-wrap items-center gap-2">
          <StatusBadge tone="active" title="The label beside this model's arrows on the chart">
            {markerLabel(name)}
          </StatusBadge>
          <span className="font-mono text-sm text-foreground">{name}</span>
        </p>
        <p className="truncate font-mono text-xs text-muted-foreground">
          {paramSummary(overlay.parameters)}
        </p>
        {overlay.status === 'running' ? (
          <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Hourglass size={16} strokeWidth={1.5} aria-hidden="true" />
            Running over the full history…
          </p>
        ) : overlay.status === 'error' ? (
          <p role="alert" className="text-xs text-destructive">
            Could not run: {overlay.error}
          </p>
        ) : (
          <Outcome overlay={overlay} />
        )}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`Remove ${name}`}
        onClick={onRemove}
        className="shrink-0"
      >
        <X size={16} strokeWidth={1.5} aria-hidden="true" />
      </Button>
    </li>
  );
}

function ParamInput({
  spec,
  value,
  error,
  onChange,
}: {
  spec: ParamSpecV2;
  value: string;
  error: string | null;
  onChange: (value: string) => void;
}) {
  const unit = unitOf(spec);
  const suffix = unit ? UNIT_PRESENTATION[unit].suffix : '';
  const id = `model-param-${spec.name}`;
  if (spec.type === 'bool') {
    return (
      <Label htmlFor={id}>
        {spec.name}
        <Select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="true">true</option>
          <option value="false">false</option>
        </Select>
      </Label>
    );
  }
  return (
    <Label htmlFor={id} title={spec.description ?? undefined}>
      <span>
        {spec.name}
        {suffix ? <span className="normal-case"> ({suffix})</span> : null}
      </span>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        className={cn(fieldClasses, error && 'border-destructive')}
        value={displayValue(spec, value)}
        min={displayBound(spec, spec.minimum)}
        max={displayBound(spec, spec.maximum)}
        step={spec.type === 'int' ? 1 : 'any'}
        aria-invalid={error ? true : undefined}
        onChange={(event) => onChange(wireValue(spec, event.target.value))}
      />
      {error ? <span className="normal-case tracking-normal text-destructive">{error}</span> : null}
    </Label>
  );
}

/**
 * Research's model workbench: pick a model, tune it, and see on the price
 * chart exactly where it would have fired on this one name.
 *
 * The question is "does this model read this stock well", which is a
 * one-ticker question -- building rules across a universe is Strategies' job.
 */
export function ModelsPanel({
  symbol,
  catalog,
  catalogReady,
  start,
  end,
  overlays,
  onApply,
  onToggle,
  onRemove,
}: {
  symbol: string;
  catalog: CatalogModel[];
  catalogReady: boolean;
  /** First bar on the chart: the model runs over everything shown. */
  start: string | null;
  end: string;
  overlays: ModelOverlay[];
  onApply: (model: CatalogModel, parameters: Record<string, unknown>) => void;
  onToggle: (key: string) => void;
  onRemove: (key: string) => void;
}) {
  const models = useMemo(() => signalModels(catalog), [catalog]);
  const [name, setName] = useState('');
  // A price model first: it marks the chart on day one, where a fundamentals
  // model fires on filings a handful of times a year.
  const model =
    models.find((m) => m.name === name) ??
    models.find((m) => m.name === DEFAULT_MODEL) ??
    models[0] ??
    null;
  const [values, setValues] = useState<Record<string, string>>({});

  // A different model brings its own declared defaults.
  useEffect(() => {
    setValues(model ? defaultValues(model.parameters) : {});
  }, [model]);

  const errors = Object.fromEntries(
    (model?.parameters ?? []).map((spec) => [spec.name, localError(spec, values[spec.name] ?? '')]),
  );
  const invalid = Object.values(errors).some(Boolean);

  const apply = () => {
    if (!model || invalid) return;
    const parameters: Record<string, unknown> = {};
    for (const spec of model.parameters) {
      const raw = values[spec.name];
      if (raw !== undefined && raw !== String(spec.default))
        parameters[spec.name] = coerce(spec, raw);
    }
    onApply(model, parameters);
  };

  const byCategory = useMemo(() => {
    const groups = new Map<string, CatalogModel[]>();
    for (const m of models) {
      const label = CATEGORY_LABELS[m.category] ?? m.category;
      groups.set(label, [...(groups.get(label) ?? []), m]);
    }
    return [...groups.entries()];
  }, [models]);

  return (
    <Panel
      icon={Sigma}
      title="Models"
      purpose={`Run a model over ${symbol}'s history and see where it would have signalled, marked on the price chart.`}
      testId="company-models"
      aside={
        overlays.length > 0 ? (
          <StatusBadge tone="idle">{overlays.length} applied</StatusBadge>
        ) : null
      }
    >
      <div className="space-y-3 p-3">
        <Label htmlFor="model-select">
          Model
          <Select
            id="model-select"
            value={model?.name ?? ''}
            disabled={!catalogReady || models.length === 0}
            onChange={(event) => setName(event.target.value)}
          >
            {!catalogReady ? <option value="">Loading models…</option> : null}
            {byCategory.map(([label, group]) => (
              <optgroup key={label} label={label}>
                {group.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </Select>
        </Label>
        {model ? (
          <p className="text-sm leading-relaxed text-muted-foreground">{model.summary}</p>
        ) : null}

        {model && model.parameters.length > 0 ? (
          <div className="grid grid-cols-2 gap-3">
            {model.parameters.map((spec) => (
              <ParamInput
                key={spec.name}
                spec={spec}
                value={values[spec.name] ?? ''}
                error={errors[spec.name]}
                onChange={(value) => setValues((current) => ({ ...current, [spec.name]: value }))}
              />
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
          <p className="font-mono text-xs text-muted-foreground">
            {start ? `${start} → ${end}` : 'Waiting for the price history'}
          </p>
          <Button type="button" disabled={!model || invalid || !start} onClick={apply}>
            <Play size={16} strokeWidth={1.5} aria-hidden="true" />
            Apply to {symbol}
          </Button>
        </div>
      </div>

      {overlays.length > 0 ? (
        <ul aria-label="Applied models" className="border-t border-border">
          {overlays.map((overlay) => (
            <OverlayRow
              key={overlay.key}
              overlay={overlay}
              onToggle={() => onToggle(overlay.key)}
              onRemove={() => onRemove(overlay.key)}
            />
          ))}
        </ul>
      ) : (
        <p className="border-t border-border px-3 py-3 text-sm text-muted-foreground">
          Nothing applied yet. Each model you apply is drawn on the chart: ▲ below a bar where it
          turned bullish, ▼ above where it turned bearish.
        </p>
      )}
    </Panel>
  );
}

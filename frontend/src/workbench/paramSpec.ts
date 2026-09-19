import type { ParamSpec } from '../api/client';

/**
 * Validation and coercion for a model's declared parameters.
 *
 * Extracted from RunConfig so the Quant Lab backtest form generates identical
 * fields from identical metadata. Two implementations of this would drift, and
 * the one that drifted would accept a value the other rejected.
 */

/** Mirrors the declared constraint for immediate feedback. The server
 *  validates independently and its rejection is authoritative. */
export function localError(spec: ParamSpec, raw: string): string | null {
  if (raw === '') return 'required';
  if (spec.type === 'int' || spec.type === 'float') {
    const value = Number(raw);
    if (Number.isNaN(value)) return 'must be a number';
    if (spec.type === 'int' && !Number.isInteger(value)) return 'must be a whole number';
    if (spec.minimum != null && value < spec.minimum) return `must be >= ${spec.minimum}`;
    if (spec.maximum != null && value > spec.maximum) return `must be <= ${spec.maximum}`;
  }
  return null;
}

export function coerce(spec: ParamSpec, raw: string): unknown {
  if (spec.type === 'int') return Number.parseInt(raw, 10);
  if (spec.type === 'float') return Number(raw);
  if (spec.type === 'bool') return raw === 'true';
  return raw;
}

/** Seeds a form from declared defaults. Nothing about names or types is known
 *  ahead of time (Constitution II). */
export function defaultValues(specs: ParamSpec[]): Record<string, string> {
  return Object.fromEntries(specs.map((spec) => [spec.name, String(spec.default)]));
}

/** Only the parameters the researcher actually changed. Omitted ones take the
 *  declared default, which is what keeps a run reproducible from its record. */
export function overridesFrom(
  specs: ParamSpec[],
  values: Record<string, string>,
): Record<string, unknown> {
  const overrides: Record<string, unknown> = {};
  for (const spec of specs) {
    const raw = values[spec.name];
    if (raw !== undefined && raw !== String(spec.default)) {
      overrides[spec.name] = coerce(spec, raw);
    }
  }
  return overrides;
}

import type { ParamSpec } from '../api/client';
import { UNIT_PRESENTATION, unitOf, type ParamSpecV2 } from '../api/types';

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

// --- Units ----------------------------------------------------------------
//
// A P/E bound is a ratio, an ROE floor is a percentage and a growth threshold
// is a percentage; a form that renders the three identically will be typed
// into wrongly (FUNDAMENTALS §6). The execution form already solves this for
// the percentages the contract stores as fractions, and these are the same two
// functions made general, so a rule that declares `unit: "fraction"` gets 15%
// on screen and 0.15 on the wire without the component knowing anything about
// that particular rule.
//
// Unit handling is not analysis: the displayed number and the stored number
// are the same quantity written two ways (Constitution V).

/** Drop the float noise 0.15 * 100 leaves behind, without rounding real digits. */
function tidy(value: number, places: number): string {
  return String(Number(value.toFixed(places)));
}

/** Wire value → what the field shows. */
export function displayValue(spec: ParamSpecV2, wire: string): string {
  const unit = unitOf(spec);
  if (unit === null || wire === '') return wire;
  const scale = UNIT_PRESENTATION[unit].scale;
  if (scale === 1) return wire;
  const parsed = Number(wire);
  return Number.isFinite(parsed) ? tidy(parsed * scale, 6) : wire;
}

/** What was typed → the value the engine is sent. */
export function wireValue(spec: ParamSpecV2, display: string): string {
  const unit = unitOf(spec);
  if (unit === null || display === '') return display;
  const scale = UNIT_PRESENTATION[unit].scale;
  if (scale === 1) return display;
  const parsed = Number(display);
  return Number.isFinite(parsed) ? tidy(parsed / scale, 10) : display;
}

/** A declared bound, expressed in the units the field is displayed in. */
export function displayBound(spec: ParamSpecV2, bound: number | null | undefined): number | undefined {
  if (bound === null || bound === undefined) return undefined;
  const unit = unitOf(spec);
  const scale = unit === null ? 1 : UNIT_PRESENTATION[unit].scale;
  return Number(tidy(bound * scale, 6));
}

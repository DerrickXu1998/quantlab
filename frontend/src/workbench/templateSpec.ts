import type { SignalTemplate } from '../quantlab/data/customRules';

/**
 * The rule builder's metadata layer.
 *
 * The form is generated from each template's `config_fields` (choices, number
 * bounds, and the composite input/operand markers) so a new template renders
 * without a frontend change. What the catalog deliberately does not ship is
 * per-indicator parameter bounds; that vocabulary is mirrored below from the
 * template contract. As everywhere in the form stack, the server validates
 * independently and its rejection is authoritative.
 */

export interface ChoiceField {
  choices: string[];
  default?: string;
}
export interface NumberField {
  type: 'int' | 'float';
  default?: number;
  minimum?: number;
  maximum?: number;
}
export interface InputField {
  sources: string[];
  indicators: string[];
}
export interface OperandField {
  operands: string[];
}

export function asChoices(field: unknown): ChoiceField | null {
  if (typeof field !== 'object' || field === null) return null;
  const choices = (field as { choices?: unknown }).choices;
  if (!Array.isArray(choices) || !choices.every((c) => typeof c === 'string')) return null;
  const def = (field as { default?: unknown }).default;
  return { choices, default: typeof def === 'string' ? def : undefined };
}

export function asNumber(field: unknown): NumberField | null {
  if (typeof field !== 'object' || field === null) return null;
  const type = (field as { type?: unknown }).type;
  if (type !== 'int' && type !== 'float') return null;
  const f = field as Record<string, unknown>;
  return {
    type,
    default: typeof f.default === 'number' ? f.default : undefined,
    minimum: typeof f.minimum === 'number' ? f.minimum : undefined,
    maximum: typeof f.maximum === 'number' ? f.maximum : undefined,
  };
}

export function isInputField(field: unknown): field is InputField {
  if (typeof field !== 'object' || field === null) return false;
  const f = field as Record<string, unknown>;
  return Array.isArray(f.sources) && Array.isArray(f.indicators);
}

export function isOperandField(field: unknown): field is OperandField {
  if (typeof field !== 'object' || field === null) return false;
  return Array.isArray((field as Record<string, unknown>).operands);
}

// --- The indicator/operand parameter vocabulary --------------------------------

export interface OperandParamSpec {
  name: string;
  type: 'int' | 'float';
  default: number;
  minimum: number;
  maximum: number;
}

const WINDOW = (def = 20, max = 400): OperandParamSpec => ({
  name: 'window',
  type: 'int',
  default: def,
  minimum: 2,
  maximum: max,
});

export const OPERAND_PARAMS: Record<string, OperandParamSpec[]> = {
  close: [],
  sma: [WINDOW()],
  ema: [WINDOW()],
  rsi: [{ name: 'period', type: 'int', default: 14, minimum: 2, maximum: 100 }],
  rolling_std: [WINDOW()],
  rolling_max: [WINDOW()],
  rolling_min: [WINDOW()],
  macd_line: [
    { name: 'fast', type: 'int', default: 12, minimum: 2, maximum: 200 },
    { name: 'slow', type: 'int', default: 26, minimum: 3, maximum: 400 },
  ],
  bollinger_upper: [
    WINDOW(20, 250),
    { name: 'num_std', type: 'float', default: 2, minimum: 0.5, maximum: 5 },
  ],
  bollinger_lower: [
    WINDOW(20, 250),
    { name: 'num_std', type: 'float', default: 2, minimum: 0.5, maximum: 5 },
  ],
};

// --- Form state -----------------------------------------------------------------

export interface InputState {
  source: string;
  indicator: string;
  params: Record<string, string>;
}
export interface OperandState {
  kind: string;
  params: Record<string, string>;
}
export type FormValue = string | InputState | OperandState;
export type FormState = Record<string, FormValue>;

function defaultParams(kind: string): Record<string, string> {
  return Object.fromEntries(
    (OPERAND_PARAMS[kind] ?? []).map((spec) => [spec.name, String(spec.default)]),
  );
}

function isInput(value: FormValue): value is InputState {
  return typeof value === 'object' && 'source' in value;
}
function isOperand(value: FormValue): value is OperandState {
  return typeof value === 'object' && 'kind' in value;
}

export function initialFormState(template: SignalTemplate): FormState {
  const state: FormState = {};
  for (const [key, field] of Object.entries(template.config_fields)) {
    const choices = asChoices(field);
    const number = asNumber(field);
    if (isInputField(field)) {
      const indicator = field.indicators[0] ?? 'sma';
      state[key] = {
        source: field.sources[0] ?? 'close',
        indicator,
        params: defaultParams(indicator),
      };
    } else if (isOperandField(field)) {
      const kind = field.operands[0] ?? 'close';
      state[key] = { kind, params: defaultParams(kind) };
    } else if (choices) {
      state[key] = choices.default ?? choices.choices[0] ?? '';
    } else if (number) {
      state[key] = number.default !== undefined ? String(number.default) : '';
    } else {
      state[key] = '';
    }
  }
  return state;
}

/** Edit prefill: the stored config back into string form state. Unknown or
 *  missing keys fall back to the template defaults. */
export function formStateFromConfig(
  template: SignalTemplate,
  config: Record<string, unknown>,
): FormState {
  const state = initialFormState(template);
  for (const [key, field] of Object.entries(template.config_fields)) {
    const value = config[key];
    const current = state[key];
    if (isInputField(field) && isInput(current) && typeof value === 'object' && value !== null) {
      const stored = value as {
        source?: string;
        indicator?: string;
        params?: Record<string, unknown>;
      };
      const source = stored.source ?? current.source;
      const indicator = stored.indicator ?? current.indicator;
      const params = defaultParams(indicator);
      for (const [name, v] of Object.entries(stored.params ?? {})) params[name] = String(v);
      state[key] = { source, indicator, params };
    } else if (
      isOperandField(field) &&
      isOperand(current) &&
      typeof value === 'object' &&
      value !== null
    ) {
      const stored = value as { kind?: string; params?: Record<string, unknown> };
      const kind = stored.kind ?? current.kind;
      const params = defaultParams(kind);
      for (const [name, v] of Object.entries(stored.params ?? {})) params[name] = String(v);
      state[key] = { kind, params };
    } else if (typeof current === 'string' && value !== undefined) {
      state[key] = String(value);
    }
  }
  return state;
}

function coerceParams(kind: string, params: Record<string, string>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const spec of OPERAND_PARAMS[kind] ?? []) {
    const raw = params[spec.name];
    if (raw === undefined || raw === '') continue;
    out[spec.name] = spec.type === 'int' ? Number.parseInt(raw, 10) : Number(raw);
  }
  return out;
}

/** The config object a template expects, from string form state. */
export function buildConfig(template: SignalTemplate, state: FormState): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(template.config_fields)) {
    const value = state[key];
    const number = asNumber(field);
    if (isInputField(field) && value && isInput(value)) {
      config[key] =
        value.source === 'indicator'
          ? {
              source: 'indicator',
              indicator: value.indicator,
              params: coerceParams(value.indicator, value.params),
            }
          : { source: value.source };
    } else if (isOperandField(field) && value && isOperand(value)) {
      const params = coerceParams(value.kind, value.params);
      config[key] =
        Object.keys(params).length > 0 ? { kind: value.kind, params } : { kind: value.kind };
    } else if (number && typeof value === 'string') {
      config[key] = number.type === 'int' ? Number.parseInt(value, 10) : Number(value);
    } else {
      config[key] = value;
    }
  }
  return config;
}

function paramError(spec: OperandParamSpec, raw: string): string | null {
  if (raw === '') return 'required';
  const value = Number(raw);
  if (Number.isNaN(value)) return 'must be a number';
  if (spec.type === 'int' && !Number.isInteger(value)) return 'must be a whole number';
  if (value < spec.minimum) return `must be >= ${spec.minimum}`;
  if (value > spec.maximum) return `must be <= ${spec.maximum}`;
  return null;
}

function numberError(spec: NumberField, raw: string): string | null {
  if (raw === '') return 'required';
  const value = Number(raw);
  if (Number.isNaN(value)) return 'must be a number';
  if (spec.type === 'int' && !Number.isInteger(value)) return 'must be a whole number';
  if (spec.minimum != null && value < spec.minimum) return `must be >= ${spec.minimum}`;
  if (spec.maximum != null && value > spec.maximum) return `must be <= ${spec.maximum}`;
  return null;
}

/** Per-field errors, keyed by field name (params as `field.param`). Mirrors the
 *  declared constraints for immediate feedback; the server re-validates. */
export function configErrors(template: SignalTemplate, state: FormState): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const [key, field] of Object.entries(template.config_fields)) {
    const value = state[key];
    const number = asNumber(field);
    // transform_window only applies under pct_change; validating a hidden
    // field would block a save the user cannot fix.
    if (key === 'transform_window' && state.transform !== 'pct_change') continue;
    if (isInputField(field) && value && isInput(value) && value.source === 'indicator') {
      for (const spec of OPERAND_PARAMS[value.indicator] ?? []) {
        const problem = paramError(spec, value.params[spec.name] ?? '');
        if (problem) errors[`${key}.${spec.name}`] = problem;
      }
    } else if (isOperandField(field) && value && isOperand(value)) {
      for (const spec of OPERAND_PARAMS[value.kind] ?? []) {
        const problem = paramError(spec, value.params[spec.name] ?? '');
        if (problem) errors[`${key}.${spec.name}`] = problem;
      }
    } else if (number && typeof value === 'string') {
      const problem = numberError(number, value);
      if (problem) errors[key] = problem;
    }
  }
  return errors;
}

// --- The plain-English preview ---------------------------------------------------

function num(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/** "14-day RSI" / "the MACD line (12/26)" / "the close". */
export function operandPhrase(kind: string, params: Record<string, unknown> = {}): string {
  const p = (name: string) => num(params[name], NaN);
  const suffix = (n: number) => (Number.isFinite(n) ? `${n}-day` : '…');
  switch (kind) {
    case 'close':
      return 'the close';
    case 'rsi':
      return `${suffix(p('period'))} RSI`;
    case 'sma':
      return `${suffix(p('window'))} SMA`;
    case 'ema':
      return `${suffix(p('window'))} EMA`;
    case 'rolling_std':
      return `${suffix(p('window'))} rolling std`;
    case 'rolling_max':
      return `${suffix(p('window'))} rolling high`;
    case 'rolling_min':
      return `${suffix(p('window'))} rolling low`;
    case 'macd_line':
      return `the MACD line (${p('fast') || '…'}/${p('slow') || '…'})`;
    case 'bollinger_upper':
      return `the upper Bollinger band (${suffix(p('window'))}, ${num(params.num_std, NaN) || '…'}σ)`;
    case 'bollinger_lower':
      return `the lower Bollinger band (${suffix(p('window'))}, ${num(params.num_std, NaN) || '…'}σ)`;
    default:
      return kind;
  }
}

function inputPhrase(config: Record<string, unknown>): string {
  const input = (config.input ?? {}) as {
    source?: string;
    indicator?: string;
    params?: Record<string, unknown>;
  };
  const base =
    input.source === 'indicator'
      ? operandPhrase(input.indicator ?? '…', input.params)
      : 'the close';
  if (config.transform === 'pct_change') {
    return `the ${num(config.transform_window, 1)}-day % change of ${base}`;
  }
  return base;
}

/**
 * The live preview sentence — the same string the rail shows under a saved
 * rule, so the builder and the list can never disagree about what a config
 * means. Generated from the config, never stored.
 */
export function describeRule(templateId: string, config: Record<string, unknown>): string {
  if (templateId === 'indicator-crossover') {
    const a = (config.a ?? {}) as { kind?: string; params?: Record<string, unknown> };
    const b = (config.b ?? {}) as { kind?: string; params?: Record<string, unknown> };
    return `Bullish when ${operandPhrase(a.kind ?? '…', a.params)} crosses above ${operandPhrase(b.kind ?? '…', b.params)}; bearish when it crosses below.`;
  }
  if (templateId === 'indicator-threshold') {
    const x = inputPhrase(config);
    const t = typeof config.threshold === 'number' ? String(config.threshold) : '…';
    const bullishOn = config.bullish_on === 'below' ? 'below' : 'above';
    switch (config.comparator) {
      case 'crosses_above':
        return `${bullishOn === 'above' ? 'Bullish' : 'Bearish'} when ${x} crosses above ${t}.`;
      case 'crosses_below':
        return `${bullishOn === 'below' ? 'Bullish' : 'Bearish'} when ${x} crosses below ${t}.`;
      case 'enters_zone':
        return `Bullish when ${x} enters the zone ${bullishOn} ${t}.`;
      case 'exits_zone':
        return `${bullishOn === 'above' ? 'Bearish' : 'Bullish'} when ${x} exits the zone ${bullishOn} ${t}.`;
      default:
        return `Signal on ${x} against ${t}.`;
    }
  }
  return templateId;
}

import type { RunRequest } from '../api/client';

/**
 * The execution-criteria half of the run form.
 *
 * Unlike the signal parameters — which are generated from whatever the model
 * declares — the execution contract is a fixed part of the run API, so its
 * fields are declared here once rather than discovered. Validation and
 * coercion mirror paramSpec so both halves of the form behave identically.
 */

export type ExecutionCriteria = NonNullable<RunRequest['execution']>;

export interface ExecutionFieldSpec {
  name: keyof ExecutionCriteria;
  label: string;
  help: string;
  kind: 'int' | 'float' | 'enum';
  /** The seed value as a string; '' on an optional field means "none". */
  fallback: string;
  /** An optional field submits `null` when left empty. */
  optional?: boolean;
  minimum?: number;
  minExclusive?: boolean;
  maximum?: number;
  choices?: readonly { value: string; label: string }[];
  /** Conditional fields render and validate only while this holds. */
  visibleWhen?: (values: Record<string, string>) => boolean;
}

export const EXECUTION_FIELDS: readonly ExecutionFieldSpec[] = [
  {
    name: 'initial_capital',
    label: 'Initial capital',
    help: 'Starting book value.',
    kind: 'float',
    fallback: '100000',
    minimum: 0,
    minExclusive: true,
  },
  {
    name: 'position_sizing',
    label: 'Position sizing',
    help: 'How each entry is sized.',
    kind: 'enum',
    fallback: 'equal_weight',
    choices: [
      { value: 'equal_weight', label: 'Equal weight per instrument' },
      { value: 'fixed_fraction', label: 'Fixed fraction of book' },
    ],
  },
  {
    name: 'fraction',
    label: 'Fraction per entry',
    help: 'Share of the book’s current value per entry.',
    kind: 'float',
    fallback: '0.1',
    minimum: 0,
    minExclusive: true,
    maximum: 1,
    visibleWhen: (values) => values.position_sizing === 'fixed_fraction',
  },
  {
    name: 'max_open_positions',
    label: 'Max open positions',
    help: 'Empty means uncapped.',
    kind: 'int',
    fallback: '',
    optional: true,
    minimum: 1,
  },
  {
    name: 'transaction_cost_bps',
    label: 'Transaction cost (bps)',
    help: 'Basis points of traded value, charged per fill.',
    kind: 'float',
    fallback: '0',
    minimum: 0,
  },
  {
    name: 'fixed_cost_per_trade',
    label: 'Fixed cost per trade',
    help: 'Currency units, charged per fill.',
    kind: 'float',
    fallback: '0',
    minimum: 0,
  },
  {
    name: 'stop_loss_pct',
    label: 'Stop loss',
    help: 'Exit this fraction below the entry — 0.1 is 10%. Empty means none.',
    kind: 'float',
    fallback: '',
    optional: true,
    minimum: 0,
    minExclusive: true,
    maximum: 1,
  },
  {
    name: 'take_profit_pct',
    label: 'Take profit',
    help: 'Exit this fraction above the entry — 0.2 is 20%. Empty means none.',
    kind: 'float',
    fallback: '',
    optional: true,
    minimum: 0,
    minExclusive: true,
  },
  {
    name: 'entry_price',
    label: 'Entry price',
    help: 'When a signal’s fill is marked.',
    kind: 'enum',
    fallback: 'same_close',
    choices: [
      { value: 'same_close', label: 'Close of the signal day' },
      { value: 'next_open', label: 'Open of the next session' },
    ],
  },
];

export function executionDefaults(): Record<string, string> {
  return Object.fromEntries(EXECUTION_FIELDS.map((spec) => [spec.name, spec.fallback]));
}

/** The fields currently on screen; hidden ones neither render nor validate. */
export function visibleExecutionFields(
  values: Record<string, string>,
): readonly ExecutionFieldSpec[] {
  return EXECUTION_FIELDS.filter((spec) => !spec.visibleWhen || spec.visibleWhen(values));
}

/** Mirrors the declared constraint for immediate feedback. The server
 *  validates independently and its rejection is authoritative. */
export function executionError(spec: ExecutionFieldSpec, raw: string): string | null {
  if (raw === '') return spec.optional ? null : 'required';
  if (spec.kind === 'enum') return null;
  const value = Number(raw);
  if (Number.isNaN(value)) return 'must be a number';
  if (spec.kind === 'int' && !Number.isInteger(value)) return 'must be a whole number';
  if (spec.minimum != null) {
    if (spec.minExclusive ? value <= spec.minimum : value < spec.minimum) {
      return `must be ${spec.minExclusive ? '>' : '>='} ${spec.minimum}`;
    }
  }
  if (spec.maximum != null && value > spec.maximum) return `must be <= ${spec.maximum}`;
  return null;
}

function coerceField(spec: ExecutionFieldSpec, raw: string): number | string | null {
  if (raw === '' && spec.optional) return null;
  if (spec.kind === 'int') return Number.parseInt(raw, 10);
  if (spec.kind === 'float') return Number(raw);
  return raw;
}

/**
 * The full criteria object, merged over the defaults. The API records the
 * effective criteria with the run and an all-defaults object is defined to
 * behave exactly like an omitted one, so sending the merged object is both
 * the cleanest typing and the most honest provenance.
 */
export function buildExecutionCriteria(values: Record<string, string>): ExecutionCriteria {
  const merged = { ...executionDefaults(), ...values };
  return Object.fromEntries(
    EXECUTION_FIELDS.map((spec) => [spec.name, coerceField(spec, merged[spec.name] ?? '')]),
  ) as unknown as ExecutionCriteria;
}

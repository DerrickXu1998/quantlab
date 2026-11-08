import type {
  AllocationField,
  CatalogModel,
  CombineLogic,
  ExecutionConfig,
  RebalanceFrequency,
  Strategy,
  StrategyComponent,
  StrategyRole,
  StrategySpec,
} from '../api/types';
import {
  ALLOCATION_FIELDS,
  DEFAULT_EXECUTION,
  REBALANCE_FREQUENCIES,
  isAllocationSizing,
  resolveAllocation,
  ROLE_LABELS,
  UNIT_PRESENTATION,
  unitOf,
  withExecutionDefaults,
  type ParamSpecV2,
} from '../api/types';
import { coerce, defaultValues, displayValue, localError } from '../workbench/paramSpec';

/**
 * The strategy the builder is editing, and the English it reads as.
 *
 * Kept out of the components on purpose: role enforcement and the summary
 * sentence are the two things most worth testing in this feature, and both are
 * pure functions of a draft plus the catalogue. Nothing here computes anything
 * analytical — a component's parameters are never evaluated against bars,
 * only named (Constitution V).
 */

// --- The draft -------------------------------------------------------------

/**
 * Parameters are held as strings while being edited, exactly as RunConfigForm
 * holds them, so `paramSpec`'s validation and coercion are the same code on
 * both surfaces rather than two implementations that drift.
 */
export interface DraftComponent {
  /** Client-side identity. The same rule can appear twice with different params. */
  id: string;
  rule_name: string;
  rule_version?: string;
  role: StrategyRole;
  weight: number;
  invert: boolean;
  values: Record<string, string>;
}

export interface Draft {
  /** The server id once saved; null for a strategy that has never been saved. */
  id: string | null;
  name: string;
  description: string;
  components: DraftComponent[];
  entry_logic: CombineLogic;
  exit_logic: CombineLogic;
  entry_threshold: number;
  exit_threshold: number;
  combine_window_days: number;
  execution: ExecutionConfig;
}

let sequence = 0;

/** Monotonic rather than random: a React key does not need entropy. */
export function nextComponentId(): string {
  sequence += 1;
  return `component-${sequence}`;
}

export function emptyDraft(name = 'Untitled strategy'): Draft {
  return {
    id: null,
    name,
    description: '',
    components: [],
    entry_logic: 'all',
    exit_logic: 'any',
    entry_threshold: 1,
    exit_threshold: 1,
    combine_window_days: 1,
    execution: { ...DEFAULT_EXECUTION },
  };
}

// --- Role enforcement ------------------------------------------------------

/**
 * §2: `roles` is what a rule advertises it can honestly do. `adx-trend-filter`
 * emits a regime state rather than a tradeable event, so it says `["filter"]`
 * and must not be wired as an entry.
 */
export function canFillRole(model: CatalogModel, role: StrategyRole): boolean {
  return model.roles.includes(role);
}

/**
 * Why a role is refused, in words — never a silently disabled control.
 *
 * A greyed-out button with no explanation reads as a bug; the user retries it,
 * concludes the app is broken, and never learns that the rule genuinely cannot
 * open a position.
 */
export function roleRefusal(model: CatalogModel, role: StrategyRole): string | null {
  if (canFillRole(model, role)) return null;
  const allowed = model.roles.map((item) => ROLE_LABELS[item].toLowerCase());
  const list =
    allowed.length > 1
      ? `${allowed.slice(0, -1).join(', ')} or ${allowed[allowed.length - 1]}`
      : allowed[0];
  if (role === 'entry' && model.roles.length === 1 && model.roles[0] === 'filter') {
    return `${model.name} reports a market state rather than a tradeable event, so it cannot open a position. Add it as a filter instead.`;
  }
  return `${model.name} advertises ${list} only, so it cannot be used as ${
    role === 'entry' ? 'an entry' : `an ${ROLE_LABELS[role].toLowerCase()}`
  }.`;
}

// --- Draft <-> spec --------------------------------------------------------

export function findModel(catalog: CatalogModel[], name: string): CatalogModel | null {
  return catalog.find((model) => model.name === name) ?? null;
}

/**
 * Whether a rule reads filed facts.
 *
 * Duplicated in spirit by `fundamentals.isFundamental`, which also accepts the
 * category; this one is deliberately the narrow test — it decides whether the
 * summary sentence makes a claim about restatements, and a rule that reads no
 * facts must not make the strategy assert one.
 */
function readsFacts(model: CatalogModel | null): boolean {
  // Both hops are optional. `requires_facts` is new, so a catalogue served by
  // a backend that predates it — or any fixture written before it — has the
  // model but not the field, and stopping the chain at `model` throws on every
  // one of them.
  return (model?.requires_facts?.length ?? 0) > 0;
}

export function componentFor(model: CatalogModel, role: StrategyRole): DraftComponent {
  return {
    id: nextComponentId(),
    rule_name: model.name,
    rule_version: model.version,
    role,
    weight: 1,
    invert: false,
    values: defaultValues(model.parameters),
  };
}

/** Per-component, per-parameter validation, reusing the shared helpers. */
export function componentErrors(
  component: DraftComponent,
  model: CatalogModel | null,
): Record<string, string> {
  if (!model) return {};
  const errors: Record<string, string> = {};
  for (const spec of model.parameters) {
    const problem = localError(spec, component.values[spec.name] ?? '');
    if (problem) errors[spec.name] = problem;
  }
  return errors;
}

export function draftHasErrors(draft: Draft, catalog: CatalogModel[]): boolean {
  return draft.components.some(
    (component) =>
      Object.keys(componentErrors(component, findModel(catalog, component.rule_name))).length > 0,
  );
}

/**
 * Non-blocking notes. §3 is explicit that a strategy with no exit component is
 * legal and that the builder warns rather than blocks — the execution criteria
 * can be the whole exit, and refusing to save that would be the tool inventing
 * a rule the engine does not have.
 */
export function draftWarnings(draft: Draft): string[] {
  const warnings: string[] = [];
  const exits = draft.components.filter((component) => component.role === 'exit');
  const execution = draft.execution;

  if (exits.length === 0) {
    const protective =
      execution.stop_loss_pct !== null ||
      execution.take_profit_pct !== null ||
      execution.trailing_stop_pct !== null ||
      execution.atr_stop_multiple !== null ||
      execution.max_holding_days !== null;
    warnings.push(
      protective
        ? 'No exit signal. Positions close only on the execution criteria — that is legal, and it is what will happen.'
        : 'No exit signal and no stop, target or holding limit. Every position will stay open to the end of the window.',
    );
  }

  const sizing = execution.position_sizing;
  if (sizing === 'signal_strength' || sizing === 'signal_inverse_volatility') {
    const entries = draft.components.filter((component) => component.role === 'entry');
    // An `all` entry, or a weighted one whose threshold needs every weight,
    // only fires when every component agrees: every signal scores 100%.
    const totalWeight = entries.reduce((total, component) => total + component.weight, 0);
    const everyoneMustAgree =
      draft.entry_logic === 'all' ||
      (draft.entry_logic === 'weighted' && draft.entry_threshold >= totalWeight);
    if (entries.length === 1 || (entries.length > 1 && everyoneMustAgree)) {
      warnings.push(
        sizing === 'signal_strength'
          ? 'Every entry signal scores 100% here (one entry component, or ALL must agree), so signal strength allocates exactly like equal active weight.'
          : 'Every entry signal scores 100% here (one entry component, or ALL must agree), so weights differ only by volatility.',
      );
    }
  }
  return warnings;
}

/**
 * Why this draft cannot run, in the order a reader should fix them. Empty when
 * it can.
 *
 * These are the strategy-level refusals of `StrategySpec.validate` on the
 * backend, checked here so Run is disabled with the reason beside it rather
 * than enabled into a server error. Warnings (above) are things the engine
 * will do that the reader may not expect; blockers are things it will not do
 * at all. Parameter ranges are {@link draftHasErrors}' and are marked on the
 * fields themselves.
 */
export function draftBlockers(draft: Draft): string[] {
  const blockers: string[] = [];
  const entries = draft.components.filter((component) => component.role === 'entry');
  const exits = draft.components.filter((component) => component.role === 'exit');

  if (draft.components.length === 0) {
    blockers.push('Add at least one rule — start with an entry signal from the catalogue.');
    return blockers;
  }
  if (entries.length === 0) {
    blockers.push(
      draft.components.every((component) => component.role === 'filter')
        ? 'Filters only gate entries — add an entry signal, or nothing will ever open a position.'
        : 'No entry signal: add one, or nothing will ever open a position.',
    );
  }
  if (draft.entry_logic === 'weighted' && entries.length > 0) {
    const available = entries.reduce((total, component) => total + component.weight, 0);
    if (draft.entry_threshold > available) {
      blockers.push(
        `Entry threshold ${draft.entry_threshold} is above the ${available} of weight available, so entries can never fire.`,
      );
    }
  }
  if (draft.exit_logic === 'weighted' && exits.length > 0) {
    const available = exits.reduce((total, component) => total + component.weight, 0);
    if (draft.exit_threshold > available) {
      blockers.push(
        `Exit threshold ${draft.exit_threshold} is above the ${available} of weight available, so signal exits can never fire.`,
      );
    }
  }
  blockers.push(...allocationBlockers(draft.execution));
  return blockers;
}

/** Set, as the backend reads it: null and absent both mean "use the default". */
function isSet<T>(value: T | null | undefined): value is T {
  return value !== null && value !== undefined;
}

const ALLOCATION_FIELD_LABELS: Record<AllocationField, string> = {
  target_exposure: 'Target exposure',
  min_allocation_score: 'Min allocation score',
  rebalance_frequency: 'Rebalance',
  rebalance_threshold: 'Rebalance threshold',
  max_turnover: 'Max turnover',
};

/**
 * The allocation combinations `ExecutionConfig.validate` refuses, with the same
 * ranges, so Run is disabled with the reason rather than sent into a 422.
 */
export function allocationBlockers(execution: ExecutionConfig): string[] {
  const blockers: string[] = [];
  if (!isAllocationSizing(execution.position_sizing)) {
    const stray = ALLOCATION_FIELDS.filter((field) => isSet(execution[field]));
    if (stray.length > 0) {
      const names = joinList(
        stray.map((field) => ALLOCATION_FIELD_LABELS[field]),
        'and',
      );
      const one = stray.length === 1;
      blockers.push(
        `${names} only ${one ? 'applies' : 'apply'} to portfolio allocation sizing (equal active, signal strength, strength ÷ volatility) — clear ${one ? 'it' : 'them'} or pick one of those modes.`,
      );
    }
    return blockers;
  }

  if (isSet(execution.sizing_value)) {
    blockers.push('Portfolio allocation sizing takes no sizing value — the targets set the size.');
  }
  const {
    target_exposure,
    min_allocation_score,
    rebalance_frequency,
    rebalance_threshold,
    max_turnover,
  } = execution;
  const finite = (value: number) => Number.isFinite(value);
  if (
    isSet(target_exposure) &&
    !(finite(target_exposure) && target_exposure > 0 && target_exposure <= 1)
  ) {
    blockers.push('Target exposure must be above 0% and at most 100%.');
  }
  if (
    isSet(min_allocation_score) &&
    !(finite(min_allocation_score) && min_allocation_score >= 0 && min_allocation_score <= 1)
  ) {
    blockers.push('Min allocation score must be between 0% and 100%.');
  }
  if (isSet(rebalance_frequency) && !REBALANCE_FREQUENCIES.includes(rebalance_frequency)) {
    blockers.push(`Rebalance must be one of ${REBALANCE_FREQUENCIES.join(', ')}.`);
  }
  if (
    isSet(rebalance_threshold) &&
    !(finite(rebalance_threshold) && rebalance_threshold >= 0 && rebalance_threshold < 1)
  ) {
    blockers.push('Rebalance threshold must be at least 0% and below 100%.');
  }
  if (isSet(max_turnover) && !(finite(max_turnover) && max_turnover > 0 && max_turnover <= 2)) {
    blockers.push('Max turnover must be above 0% and at most 200%, or blank for no cap.');
  }
  if (
    execution.position_sizing === 'signal_inverse_volatility' &&
    !(Number.isInteger(execution.atr_period) && execution.atr_period >= 2)
  ) {
    blockers.push('Volatility lookback must be a whole number of at least 2 bars.');
  }
  return blockers;
}

export function draftToSpec(draft: Draft, catalog: CatalogModel[]): StrategySpec {
  return {
    name: draft.name.trim() || 'Untitled strategy',
    description: draft.description,
    components: draft.components.map((component) => {
      const model = findModel(catalog, component.rule_name);
      const parameters: Record<string, unknown> = {};
      for (const spec of model?.parameters ?? []) {
        const raw = component.values[spec.name];
        if (raw !== undefined && raw !== '') parameters[spec.name] = coerce(spec, raw);
      }
      const built: StrategyComponent = {
        rule_name: component.rule_name,
        parameters,
        role: component.role,
      };
      if (component.rule_version) built.rule_version = component.rule_version;
      // `weight` is only editable, and only sent, under weighted logic. The
      // allocation score reads it too, but a weight the user cannot see must
      // not tilt the allocation, so otherwise every component counts as 1.
      if (draft.entry_logic === 'weighted' || draft.exit_logic === 'weighted') {
        built.weight = component.weight;
      }
      if (component.invert) built.invert = true;
      return built;
    }),
    entry_logic: draft.entry_logic,
    exit_logic: draft.exit_logic,
    entry_threshold: draft.entry_threshold,
    exit_threshold: draft.exit_threshold,
    combine_window_days: draft.combine_window_days,
    execution: draft.execution,
  };
}

export function specToDraft(spec: Strategy | StrategySpec, catalog: CatalogModel[]): Draft {
  const id = 'id' in spec ? spec.id : null;
  return {
    id,
    name: spec.name,
    description: spec.description ?? '',
    components: spec.components.map((component) => {
      const model = findModel(catalog, component.rule_name);
      const values = model ? defaultValues(model.parameters) : {};
      for (const [key, value] of Object.entries(component.parameters ?? {})) {
        values[key] = String(value);
      }
      return {
        id: nextComponentId(),
        rule_name: component.rule_name,
        rule_version: component.rule_version ?? model?.version,
        role: component.role,
        weight: component.weight ?? 1,
        invert: component.invert ?? false,
        values,
      };
    }),
    entry_logic: spec.entry_logic,
    exit_logic: spec.exit_logic,
    entry_threshold: spec.entry_threshold ?? 1,
    exit_threshold: spec.exit_threshold ?? 1,
    combine_window_days: spec.combine_window_days,
    execution: withExecutionDefaults(spec.execution),
  };
}

// --- The plain-English summary --------------------------------------------

function percent(fraction: number): string {
  const value = fraction * 100;
  return `${Number.isInteger(value) ? value : Number(value.toFixed(2))}%`;
}

function joinList(parts: string[], conjunction: 'and' | 'or'): string {
  if (parts.length === 0) return '';
  if (parts.length === 1) return parts[0];
  return `${parts.slice(0, -1).join(', ')} ${conjunction} ${parts[parts.length - 1]}`;
}

/**
 * A bound, read as a bound.
 *
 * "max 20" is a field name and a number; "at most 20" is English, and this
 * sentence is the one place the strategy has to read as English. The rule is a
 * naming convention applied uniformly to every registered rule — never a table
 * of known parameters, which would go stale the moment a rule was added
 * (Constitution II).
 */
function boundWord(name: string): string | null {
  if (/^min(_|$)/.test(name) || /_min$/.test(name)) return 'at least';
  if (/^max(_|$)/.test(name) || /_max$/.test(name)) return 'at most';
  return null;
}

/**
 * "period 14, oversold 25", "at most 20×", "at least 15%" — the parameters the
 * user actually set, in the units they were declared in.
 *
 * The unit matters most here: a sentence that says a margin filter is set to
 * 0.15 when the field says 15 describes a strategy the user did not build.
 */
function parameterPhrase(component: DraftComponent, model: CatalogModel | null): string {
  const specs: ParamSpecV2[] = model?.parameters ?? [];
  const parts = specs
    .map((spec) => {
      const raw = component.values[spec.name];
      if (raw === undefined || raw === '') return null;
      const unit = unitOf(spec);
      const shown =
        unit === null ? raw : UNIT_PRESENTATION[unit].inSentence(displayValue(spec, raw));
      const bound = boundWord(spec.name);
      return bound === null ? `${spec.name} ${shown}` : `${bound} ${shown}`;
    })
    .filter((part): part is string => part !== null);
  return parts.length === 0 ? '' : ` (${parts.join(', ')})`;
}

/**
 * One component, named the way its own registry describes it.
 *
 * The English comes from the rule's `summary`, not from a lookup table here:
 * a table would have to be extended every time a rule is registered, which is
 * exactly the hardcoding Constitution II forbids, and it would go stale
 * silently when a rule's behaviour changed.
 */
export function describeComponent(component: DraftComponent, model: CatalogModel | null): string {
  const summary = (model?.summary ?? component.rule_name).replace(/\.$/, '');
  const phrase = `${summary}${parameterPhrase(component, model)}`;
  return component.invert ? `the opposite of ${phrase}` : phrase;
}

function entryClause(draft: Draft, catalog: CatalogModel[]): string {
  const entries = draft.components.filter((component) => component.role === 'entry');
  if (entries.length === 0) {
    return 'Nothing opens a position yet — add an entry signal.';
  }

  const described = entries.map((component) =>
    describeComponent(component, findModel(catalog, component.rule_name)),
  );

  if (entries.length === 1) return `Enter when ${described[0]} fires`;

  switch (draft.entry_logic) {
    case 'all':
      return `Enter when ALL of ${joinList(described, 'and')} fire`;
    case 'any':
      return `Enter when ANY of ${joinList(described, 'or')} fires`;
    case 'majority':
      return `Enter when MORE THAN HALF of ${joinList(described, 'and')} fire`;
    case 'weighted': {
      const weighted = entries.map(
        (component, index) => `${described[index]} ×${component.weight}`,
      );
      return `Enter when the firing signals are worth ${draft.entry_threshold} or more in total (${joinList(weighted, 'and')})`;
    }
  }
}

function filterClause(draft: Draft, catalog: CatalogModel[]): string {
  const filters = draft.components.filter((component) => component.role === 'filter');
  if (filters.length === 0) return '';
  const described = filters.map((component) =>
    describeComponent(component, findModel(catalog, component.rule_name)),
  );
  // Every filter must hold: §3 says an entry is suppressed unless all of them
  // are active, so "and" here is not a stylistic choice.
  return `, while ${joinList(described, 'and')} ${filters.length === 1 ? 'holds' : 'all hold'}`;
}

function protectiveClauses(execution: ExecutionConfig): string[] {
  const parts: string[] = [];
  if (execution.stop_loss_pct !== null) parts.push(`a ${percent(execution.stop_loss_pct)} stop`);
  if (execution.trailing_stop_pct !== null) {
    parts.push(`a ${percent(execution.trailing_stop_pct)} trailing stop`);
  }
  if (execution.take_profit_pct !== null) {
    parts.push(`a ${percent(execution.take_profit_pct)} target`);
  }
  if (execution.atr_stop_multiple !== null) {
    parts.push(`a ${execution.atr_stop_multiple}× ATR(${execution.atr_period}) stop`);
  }
  if (execution.max_holding_days !== null) {
    parts.push(`${execution.max_holding_days} bars held at most`);
  }
  return parts;
}

function exitClause(draft: Draft, catalog: CatalogModel[]): string {
  const exits = draft.components.filter((component) => component.role === 'exit');
  const protective = protectiveClauses(draft.execution);
  const described = exits.map((component) =>
    describeComponent(component, findModel(catalog, component.rule_name)),
  );

  if (exits.length === 0) {
    return protective.length === 0
      ? 'Nothing closes a position: every trade runs to the end of the window.'
      : `Exit on ${joinList(protective, 'or')}.`;
  }

  const signal =
    exits.length === 1
      ? `Exit when ${described[0]} fires`
      : draft.exit_logic === 'all'
        ? `Exit when ALL of ${joinList(described, 'and')} fire`
        : draft.exit_logic === 'majority'
          ? `Exit when MORE THAN HALF of ${joinList(described, 'and')} fire`
          : draft.exit_logic === 'weighted'
            ? `Exit when the firing exit signals are worth ${draft.exit_threshold} or more (${joinList(
                exits.map((component, index) => `${described[index]} ×${component.weight}`),
                'and',
              )})`
            : `Exit on ANY of ${joinList(described, 'or')}`;

  return protective.length === 0 ? `${signal}.` : `${signal}, or on ${joinList(protective, 'or')}.`;
}

const REBALANCE_PHRASE: Record<RebalanceFrequency, string> = {
  on_signal: 'whenever a signal opens, changes or closes',
  daily: 'every session',
  weekly: 'on the first session of each week',
  monthly: 'on the first session of each month',
};

/**
 * How a shared-capital mode splits the book, in English; null for the
 * independent modes, whose sizing the sentence has never described.
 */
export function describeAllocation(execution: ExecutionConfig): string | null {
  const mode = execution.position_sizing;
  if (!isAllocationSizing(mode)) return null;
  const settings = resolveAllocation(execution);
  const exposure = percent(settings.target_exposure);
  // Equal scores tie, and ties go alphabetically: said, because a cap then
  // picks names by symbol rather than by conviction.
  const names =
    execution.max_positions === null
      ? 'every active signal'
      : `at most ${execution.max_positions} active ${execution.max_positions === 1 ? 'signal' : 'signals'} (strongest first, ties by symbol)`;
  const how =
    mode === 'equal_active'
      ? `equally across ${names}`
      : mode === 'signal_strength'
        ? `across ${names} in proportion to signal strength (the share of entry components that agree)`
        : `across ${names} in proportion to signal strength divided by trailing ${execution.atr_period}-bar volatility`;
  const parts = [`Shares ${exposure} of the book ${how}`];
  if (execution.max_position_pct < 1)
    parts.push(`at most ${percent(execution.max_position_pct)} in any one name`);
  if (settings.min_allocation_score > 0) {
    parts.push(`ignoring signals scoring below ${percent(settings.min_allocation_score)}`);
  }
  const rebalance = [
    `rebalancing open positions ${REBALANCE_PHRASE[settings.rebalance_frequency]}`,
  ];
  if (settings.rebalance_threshold > 0) {
    rebalance.push(`skipping drifts under ${percent(settings.rebalance_threshold)}`);
  }
  if (settings.max_turnover !== null) {
    rebalance.push(`trading at most ${percent(settings.max_turnover)} turnover at a time`);
  }
  return `${parts.join(', ')}, ${joinList(rebalance, 'and')} — so one signal can resize the other positions.`;
}

/**
 * The strategy, in a sentence a non-expert can check against what they meant.
 *
 * This is the single most load-bearing piece of UX in the builder: every other
 * control states a fact about one field, and only this says what the whole
 * assembly will do. It is regenerated from the draft on every keystroke rather
 * than written once and edited, so it cannot describe a strategy that is no
 * longer the one on screen.
 */
export function describeStrategy(draft: Draft, catalog: CatalogModel[]): string {
  const sentences: string[] = [];
  const entry = entryClause(draft, catalog);
  const hasEntry = draft.components.some((component) => component.role === 'entry');

  sentences.push(hasEntry ? `${entry}${filterClause(draft, catalog)}.` : entry);

  if (draft.combine_window_days > 1) {
    sentences.push(
      `Components count as agreeing if they fire within ${draft.combine_window_days} bars of each other.`,
    );
  }

  sentences.push(exitClause(draft, catalog));

  sentences.push(
    draft.execution.allow_shorts
      ? 'A bearish entry opens a short; long and short are both in play.'
      : 'Long only — bearish signals are ignored for entry.',
  );

  const allocation = describeAllocation(draft.execution);
  if (allocation) sentences.push(allocation);

  // The point-in-time rule, said in the sentence the user reads back rather
  // than only in the run's assumptions (FUNDAMENTALS §5.4). It appears only
  // when a component actually reads filings, because a claim about
  // restatements on a purely technical strategy is noise.
  if (draft.components.some((component) => readsFacts(findModel(catalog, component.rule_name)))) {
    sentences.push(
      'Fundamentals are point-in-time on the filing date: a restated figure applies from its own filing forward and never backwards, and a name with no filing is gated out rather than treated as cheap.',
    );
  }

  return sentences.join(' ');
}

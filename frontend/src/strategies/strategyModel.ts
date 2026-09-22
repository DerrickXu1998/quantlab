import type {
  CatalogModel,
  CombineLogic,
  ExecutionConfig,
  Strategy,
  StrategyComponent,
  StrategyRole,
  StrategySpec,
} from '../api/types';
import {
  DEFAULT_EXECUTION,
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
  const entries = draft.components.filter((component) => component.role === 'entry');
  const execution = draft.execution;

  if (entries.length === 0) {
    warnings.push('No entry signal: nothing will ever open a position.');
  }
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
  if (draft.components.length > 0 && draft.components.every((c) => c.role === 'filter')) {
    warnings.push('Filters only gate entries — a strategy of nothing but filters never trades.');
  }
  if (draft.entry_logic === 'weighted') {
    const available = entries.reduce((total, component) => total + component.weight, 0);
    if (draft.entry_threshold > available) {
      warnings.push(
        `Entry threshold ${draft.entry_threshold} is above the ${available} of weight available, so entries can never fire.`,
      );
    }
  }
  if (draft.exit_logic === 'weighted') {
    const available = exits.reduce((total, component) => total + component.weight, 0);
    if (exits.length > 0 && draft.exit_threshold > available) {
      warnings.push(
        `Exit threshold ${draft.exit_threshold} is above the ${available} of weight available, so signal exits can never fire.`,
      );
    }
  }
  return warnings;
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
      // `weight` is only read by weighted logic; sending it regardless would
      // put a number in the record that had no effect on the run.
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

import type {
  CatalogModel,
  ConceptCoverage,
  FundamentalFact,
  FundamentalsCoverage,
} from '../api/types';
import type { Draft, DraftComponent } from './strategyModel';
import { findModel } from './strategyModel';

/**
 * What the builder needs to know about fundamentals, as pure functions.
 *
 * Kept out of the components for the same reason `strategyModel` is: the
 * coverage answer is the single most consequential sentence on the screen —
 * "7 of your 40 instruments have no fundamentals and will never trade" — and a
 * claim of that weight has to be testable without a DOM.
 *
 * Nothing here computes anything analytical. It intersects sets of symbols,
 * compares two dates, and orders rows by the point-in-time rule. Every value,
 * ratio and staleness comes off the wire (Constitution V, FUNDAMENTALS §4).
 */

/**
 * Whether a rule reads filed facts.
 *
 * `requires_facts` first, category second. The category is how the catalogue
 * groups a rule for a human; the declared concepts are what the runner
 * actually loads, and they are what decides whether an instrument with no
 * filings can ever trade this strategy.
 */
export function isFundamental(model: CatalogModel | null): boolean {
  if (!model) return false;
  return model.requires_facts.length > 0 || model.category === 'fundamental';
}

export function fundamentalComponents(draft: Draft, catalog: CatalogModel[]): DraftComponent[] {
  return draft.components.filter((component) =>
    isFundamental(findModel(catalog, component.rule_name)),
  );
}

/** Every concept the draft's components declare, de-duplicated and ordered. */
export function requiredConcepts(draft: Draft, catalog: CatalogModel[]): string[] {
  const concepts = new Set<string>();
  for (const component of draft.components) {
    const model = findModel(catalog, component.rule_name);
    for (const concept of model?.requires_facts ?? []) concepts.add(concept);
  }
  return [...concepts].sort();
}

/** `operating_cash_flow` → `operating cash flow`. Presentation only. */
export function conceptLabel(concept: string): string {
  return concept.replace(/_/g, ' ');
}

export function conceptCoverage(
  coverage: FundamentalsCoverage | null,
  concept: string,
): ConceptCoverage | null {
  return coverage?.concepts.find((entry) => entry.concept === concept) ?? null;
}

/**
 * Does a concept's real coverage window miss the run window entirely?
 *
 * §5.2: the FINRA short-volume concepts begin 2026-08-20, so a backtest over
 * 2015 that filters on them matches nothing — silently, and indistinguishably
 * from a strategy that was simply selective. Two date comparisons, against a
 * window the server reported; nothing is inferred and nothing is hardcoded.
 */
export function windowMissesCoverage(
  entry: ConceptCoverage | null,
  start: string,
  end: string,
): boolean {
  if (!entry || !entry.first_filed || !entry.last_filed) return false;
  return entry.last_filed < start || entry.first_filed > end;
}

export interface CoverageGap {
  /** Selected instruments that can never satisfy the fundamental gate. */
  missing: string[];
  /** How many instruments were selected in total. */
  total: number;
  /**
   * How the answer was reached.
   *
   * `concept` means the server enumerated which names have each concept, so
   * the gap is exact for the concepts this strategy reads. `any-fact` means it
   * only said which names have filings at all, so the gap is a floor: a name
   * counted as covered may still be missing the particular concept. The
   * difference is stated on screen rather than smoothed over.
   */
  basis: 'concept' | 'any-fact';
}

function intersects(selected: string[], covered: Set<string>): string[] {
  return selected.filter((symbol) => !covered.has(symbol));
}

/**
 * Which of the selected instruments cannot trade this strategy.
 *
 * Returns null when the server has not said enough to answer — which is a
 * third state, not zero. "We could not check" and "all of them are covered"
 * must never render the same way (§5.1).
 */
export function coverageGap(
  selected: string[],
  concepts: string[],
  coverage: FundamentalsCoverage | null,
): CoverageGap | null {
  if (!coverage || selected.length === 0) return null;

  // Concept-exact, when the server enumerated the names per concept. A name
  // missing any one required concept has an undefined ratio and a shut gate
  // (§5.5), so the gaps union rather than intersect.
  const perConcept = concepts
    .map((concept) => conceptCoverage(coverage, concept))
    .filter((entry): entry is ConceptCoverage => entry !== null);
  if (concepts.length > 0 && perConcept.length === concepts.length) {
    const enumerated = perConcept.filter((entry) => Array.isArray(entry.symbols));
    if (enumerated.length === perConcept.length) {
      const missing = new Set<string>();
      for (const entry of enumerated) {
        for (const symbol of intersects(selected, new Set(entry.symbols))) missing.add(symbol);
      }
      return {
        missing: selected.filter((symbol) => missing.has(symbol)),
        total: selected.length,
        basis: 'concept',
      };
    }
  }

  if (coverage.symbols_without_facts) {
    const without = new Set(coverage.symbols_without_facts);
    return {
      missing: selected.filter((symbol) => without.has(symbol)),
      total: selected.length,
      basis: 'any-fact',
    };
  }

  if (coverage.symbols_with_facts) {
    return {
      missing: intersects(selected, new Set(coverage.symbols_with_facts)),
      total: selected.length,
      basis: 'any-fact',
    };
  }

  return null;
}

/**
 * The sentence §5.1 asks for, verbatim in shape.
 *
 * "will never trade", not "may find no trades": a name with no filings cannot
 * open a position under a fundamental gate, and softening that is how a user
 * reads an empty result as a verdict on the strategy.
 */
export function coverageSentence(gap: CoverageGap): string {
  if (gap.missing.length === 0) {
    return `All ${gap.total} selected instrument${gap.total === 1 ? '' : 's'} ${
      gap.total === 1 ? 'has' : 'have'
    } fundamentals.`;
  }
  const noun = gap.missing.length === 1 ? 'instrument has' : 'instruments have';
  return `${gap.missing.length} of your ${gap.total} selected ${noun} no fundamentals and will never trade.`;
}

// --- The point-in-time reading ---------------------------------------------

export interface ConceptHistory {
  concept: string;
  /** The row the PIT rule selects on the as-of date. */
  inForce: FundamentalFact;
  /**
   * Everything else knowable on that date, newest filing first.
   *
   * A later filing of a period already filed is a restatement; that is not a
   * derived label but the literal content of the two rows, which is why the
   * inspector can show it as what it is.
   */
  superseded: FundamentalFact[];
}

/** Later filing first; same filing date, later period first. */
function byPitOrder(a: FundamentalFact, b: FundamentalFact): number {
  if (a.period_end !== b.period_end) return a.period_end < b.period_end ? 1 : -1;
  if (a.filed_at !== b.filed_at) return a.filed_at < b.filed_at ? 1 : -1;
  return 0;
}

/**
 * Group the served rows by concept and pick the one in force.
 *
 * The server says which row that is when it can (`in_force`); when it does
 * not, the fallback is §2's ordering — greatest `period_end`, ties broken on
 * greatest `filed_at`. That is a sort, not a calculation: no value is derived,
 * combined or rescaled anywhere in this file.
 */
export function groupByConcept(facts: FundamentalFact[]): ConceptHistory[] {
  const byConcept = new Map<string, FundamentalFact[]>();
  for (const fact of facts) {
    const bucket = byConcept.get(fact.concept) ?? [];
    bucket.push(fact);
    byConcept.set(fact.concept, bucket);
  }

  return [...byConcept.entries()]
    .map(([concept, rows]) => {
      const ordered = [...rows].sort(byPitOrder);
      const declared = ordered.find((row) => row.in_force === true);
      const inForce = declared ?? ordered[0];
      return {
        concept,
        inForce,
        superseded: ordered.filter((row) => row !== inForce),
      };
    })
    .sort((a, b) => a.concept.localeCompare(b.concept));
}

/**
 * Is this row an earlier or later filing of a period already shown?
 *
 * Purely a comparison of the two rows' period labels — the definition of a
 * restatement in §2, not an inference about one.
 */
export function isRestatementOf(row: FundamentalFact, inForce: FundamentalFact): boolean {
  return row.period_end === inForce.period_end && row.filed_at !== inForce.filed_at;
}

/**
 * Whether a later filing of the same period changed the number or only
 * repeated it.
 *
 * Caterpillar's FY2023 revenue is filed three times with the same value (§2);
 * most rows in this table are comparatives, not corrections. Saying which is
 * which is an equality test between two served values — no quantity is
 * derived, combined or rescaled.
 */
export function restatementKind(
  row: FundamentalFact,
  inForce: FundamentalFact,
): 'refiled' | 'restated' {
  return row.value === inForce.value ? 'refiled' : 'restated';
}

/**
 * A filing carrying a period label that ends after the filing date.
 *
 * 710 rows (0.012%) are like this and they are harmless under a rule that keys
 * on `filed_at`. §2 is explicit that they are surfaced rather than dropped:
 * discarding data because it looks strange is how a clean dataset ends up
 * being a wrong one.
 */
export function isForwardDated(fact: FundamentalFact): boolean {
  return fact.filed_at < fact.period_end;
}

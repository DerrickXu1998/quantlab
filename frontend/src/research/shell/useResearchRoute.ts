import { useCallback } from 'react';
import { replaceRoute, useRoute } from '../../chrome/router';

/**
 * The three modes, in the order the work happens.
 *
 * Screen narrows a universe, Company studies one name, Test puts a thesis
 * against history. `company` is the default rather than `screen` because it is
 * the object the destination was missing and the one whose first action —
 * type a symbol — needs no explanation (docs/RESEARCH.md §4).
 */
export const RESEARCH_MODES = ['company', 'screen', 'test'] as const;

export type ResearchMode = (typeof RESEARCH_MODES)[number];

export const DEFAULT_MODE: ResearchMode = 'company';

export interface ResearchRoute {
  mode: ResearchMode;
  /** The instrument the Company mode is looking at, when one is chosen. */
  symbol: string | null;
  /**
   * The date the accounts are read as of, when the address carries one.
   *
   * Null means "the view decides", which is today. Carried here because a
   * company is only worth bookmarking together with the date it was read
   * on -- the same symbol on two dates is two different answers, so a link
   * that drops the date quietly answers a different question.
   */
  asOf: string | null;
  setAsOf: (asOf: string) => void;
  setMode: (mode: ResearchMode) => void;
  /** Select a name; from Screen this also walks the user over to Company. */
  selectSymbol: (symbol: string, options?: { switchToCompany?: boolean }) => void;
}

function parseMode(raw: string | null): ResearchMode {
  return (RESEARCH_MODES as readonly string[]).includes(raw ?? '')
    ? (raw as ResearchMode)
    : DEFAULT_MODE;
}

/**
 * Research state lives in the address bar.
 *
 * Not in component state, because the two things a researcher wants to keep
 * are exactly the two things component state loses: a company worth coming
 * back to, and a view worth sending to somebody. `#/research?mode=company&
 * symbol=CAT.US` is a bookmark, and it survives a refresh.
 *
 * `replaceRoute` rather than `navigate`: switching mode is adjusting the view,
 * not travelling. Pushing a history entry for every tab click would make the
 * back button walk the user through their own tab presses instead of taking
 * them back to where they came from.
 */
export function useResearchRoute(): ResearchRoute {
  const route = useRoute();
  const onResearch = route.destination === 'research';

  const mode = parseMode(onResearch ? route.params.get('mode') : null);

  // `instrument` is the Market destination's long-standing "Signals for X"
  // handoff. It is read as an alias rather than migrated, so a link built
  // before this change still lands on the right company.
  const symbol = onResearch
    ? (route.params.get('symbol') ?? route.params.get('instrument'))
    : null;

  const asOf = onResearch ? route.params.get('as_of') : null;

  const write = useCallback(
    (next: { mode?: ResearchMode; symbol?: string | null; asOf?: string | null }) => {
      const params = new URLSearchParams();
      const nextMode = next.mode ?? mode;
      if (nextMode !== DEFAULT_MODE) params.set('mode', nextMode);
      const nextSymbol = next.symbol === undefined ? symbol : next.symbol;
      if (nextSymbol) params.set('symbol', nextSymbol);
      const nextAsOf = next.asOf === undefined ? asOf : next.asOf;
      if (nextAsOf) params.set('as_of', nextAsOf);
      replaceRoute('research', params);
    },
    [mode, symbol, asOf],
  );

  return {
    mode,
    symbol: symbol && symbol.length > 0 ? symbol : null,
    asOf: asOf && asOf.length > 0 ? asOf : null,
    setAsOf: useCallback((next: string) => write({ asOf: next }), [write]),
    setMode: useCallback((next: ResearchMode) => write({ mode: next }), [write]),
    selectSymbol: useCallback(
      (next: string, options?: { switchToCompany?: boolean }) =>
        write({
          symbol: next,
          ...(options?.switchToCompany === false ? {} : { mode: 'company' }),
        }),
      [write],
    ),
  };
}

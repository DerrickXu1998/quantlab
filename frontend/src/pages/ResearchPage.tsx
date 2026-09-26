import { CompanyView } from '../research/company/CompanyView';
import { ScreenView } from '../research/screen/ScreenView';
import { ResearchShell } from '../research/shell/ResearchShell';
import { useResearchRoute } from '../research/shell/useResearchRoute';
import { replaceRoute, useRoute } from '../chrome/router';
import { useEffect } from 'react';

/**
 * The Research destination.
 *
 * Replaces the dockable signal workspace. The previous shell opened onto a
 * 285,990-row signal table under seven `FLOAT …` buttons, with no statement
 * anywhere of what the destination was for; the panels were named after the
 * Postgres tables behind them. The diagnosis and the evidence are in
 * docs/RESEARCH.md.
 *
 * Three modes, one mounted at a time, each carrying its own purpose line.
 * `useResearchRoute` keeps mode and symbol in the address bar so a company is
 * a bookmark, and so the Market destination's existing `?instrument=` handoff
 * still lands on the right name.
 */
export function ResearchPage() {
  const { mode, symbol, asOf, setMode, setAsOf, selectSymbol } = useResearchRoute();
  const route = useRoute();
  const legacyTest = route.destination === 'research' && route.params.get('mode') === 'test';

  // Research's old Test mode ran one rule over many names -- that is a
  // strategy, so a bookmark to it now lands in Strategies.
  useEffect(() => {
    if (legacyTest) replaceRoute('strategies', new URLSearchParams());
  }, [legacyTest]);

  return (
    <ResearchShell mode={mode} onModeChange={setMode}>
      {mode === 'company' ? (
        <CompanyView
          symbol={symbol}
          onSelectSymbol={(next) => selectSymbol(next)}
          asOf={asOf ?? undefined}
          onAsOfChange={setAsOf}
        />
      ) : (
        <ScreenView onSelectSymbol={(next) => selectSymbol(next)} />
      )}
    </ResearchShell>
  );
}

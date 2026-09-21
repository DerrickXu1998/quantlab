import { CompanyView } from '../research/company/CompanyView';
import { ScreenView } from '../research/screen/ScreenView';
import { TestView } from '../research/test/TestView';
import { ResearchShell } from '../research/shell/ResearchShell';
import { useResearchRoute } from '../research/shell/useResearchRoute';

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
  const { mode, symbol, setMode, selectSymbol } = useResearchRoute();

  return (
    <ResearchShell mode={mode} onModeChange={setMode}>
      {mode === 'company' ? (
        <CompanyView symbol={symbol} onSelectSymbol={(next) => selectSymbol(next)} />
      ) : mode === 'screen' ? (
        <ScreenView onSelectSymbol={(next) => selectSymbol(next)} />
      ) : (
        <TestView />
      )}
    </ResearchShell>
  );
}

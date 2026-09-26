import { Ban, Check, Layers } from 'lucide-react';
import { ScrollRegion } from '../../components/ui/layout';
import { conceptLabel, formatCount } from '../format';
import { Panel, PanelState } from './Panel';
import type { ReadStatus } from './useCompany';

export interface CoveragePanelProps {
  symbol: string;
  available: string[];
  missing: string[];
  status: ReadStatus;
  message: string | null;
  onRetry: () => void;
}

/**
 * Coverage, stated rather than implied.
 *
 * The failure this panel exists to prevent: a company with no `gross_profit`
 * row renders as a company whose gross profit is nothing, and a screen over
 * gross margin then reads as "few names qualified" when the truth is "most were
 * never measured" (docs/RESEARCH.md §2). So the concepts this name has *never
 * filed* are listed by name, with the words "never filed" on them, rather than
 * being left as gaps for the reader to interpret.
 */
export function CoveragePanel({
  symbol,
  available,
  missing,
  status,
  message,
  onRetry,
}: CoveragePanelProps) {
  const nothingAtAll = status === 'ready' && available.length === 0;

  return (
    <Panel
      icon={Layers}
      title="Coverage"
      purpose="Which accounting concepts this name has ever filed, and which it never has. An absent concept was never filed — it is not a zero."
      testId="company-coverage"
      fill
      aside={
        status === 'ready' ? (
          <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            {formatCount(available.length)} / {formatCount(available.length + missing.length)}
          </span>
        ) : null
      }
    >
      {status !== 'ready' ? (
        <PanelState
          status={status}
          message={message}
          subject="this name's coverage"
          route="GET /instruments/{symbol}/overview"
          onRetry={onRetry}
          testId="company-coverage-state"
        />
      ) : (
        <ScrollRegion className="p-3" testId="company-coverage-body">
          {nothingAtAll ? (
            <div
              data-testid="company-coverage-none"
              className="rounded-sm border border-dashed border-border px-3 py-4"
            >
              <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                No fundamentals at all
              </p>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                {symbol} has never filed any mapped concept. Sixty-four of the 644 catalogued
                instruments are in this position. A strategy with a fundamental filter{' '}
                <span className="text-foreground">cannot trade</span> this name — which is a
                different outcome from finding no trades, and indistinguishable from it in a result.
              </p>
            </div>
          ) : (
            <ConceptGroup
              tone="filed"
              title={`Filed — ${formatCount(available.length)}`}
              blurb="At least one filing exists for each of these, though not necessarily before the as-of date."
              concepts={available}
              testId="company-coverage-filed"
            />
          )}

          <div className="mt-4">
            <ConceptGroup
              tone="never"
              title={`Never filed — ${formatCount(missing.length)}`}
              blurb={
                missing.length === 0
                  ? `${symbol} has filed every concept this warehouse maps.`
                  : 'No filing has ever carried these. Any ratio built on one of them is unmeasurable for this name, not zero.'
              }
              concepts={missing}
              testId="company-coverage-missing"
            />
          </div>
        </ScrollRegion>
      )}
    </Panel>
  );
}

function ConceptGroup({
  tone,
  title,
  blurb,
  concepts,
  testId,
}: {
  tone: 'filed' | 'never';
  title: string;
  blurb: string;
  concepts: string[];
  testId: string;
}) {
  const Icon = tone === 'filed' ? Check : Ban;
  return (
    <div data-testid={testId}>
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {title}
      </p>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{blurb}</p>
      {concepts.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {concepts.map((concept) => (
            <li
              key={concept}
              title={
                tone === 'filed'
                  ? `${conceptLabel(concept)} has been filed by this name.`
                  : `${conceptLabel(concept)} has never been filed by this name. Unmeasurable, not zero.`
              }
              className={
                tone === 'filed'
                  ? 'flex items-center gap-1 rounded-sm border border-primary/40 px-1.5 py-px text-xs text-primary'
                  : 'flex items-center gap-1 rounded-sm border border-dashed border-border px-1.5 py-px text-xs text-muted-foreground'
              }
            >
              <Icon size={16} strokeWidth={1.5} aria-hidden="true" className="h-3 w-3" />
              {conceptLabel(concept)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

import { Search } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { EmptyState } from '../../components/ui/empty-state';
import { FillColumn, ScrollRegion, StatGrid } from '../../components/ui/layout';
import { StatusBadge } from '../../components/ui/status-badge';
import { useInstrumentFacts } from '../../strategies/useFundamentals';
import { NOT_APPLICABLE, formatCount, formatPrice } from '../format';
import { AsFiledPanel } from './AsFiledPanel';
import { AsOfControl } from './AsOfControl';
import { CoveragePanel } from './CoveragePanel';
import { PricePanel } from './PricePanel';
import { SignalHistoryPanel } from './SignalHistoryPanel';
import { SymbolPicker, SymbolPickerRetry } from './SymbolPicker';
import {
  todayISO,
  useAsFiledRows,
  useCompanyOverview,
  useCompanyPrices,
  useInstruments,
  type ReadStatus,
} from './useCompany';

export interface CompanyViewProps {
  symbol: string | null;
  onSelectSymbol: (symbol: string) => void;
  /** The as-of date, when the caller keeps it (the route does). */
  asOf?: string;
  onAsOfChange?: (asOf: string) => void;
}

/**
 * One company, as of one date.
 *
 * This is the object the product did not have. Everything an equity researcher
 * does hangs off a company, and until now the only route to one was clicking a
 * signal row that happened to name it — you could stumble onto Caterpillar but
 * you could not look it up (docs/RESEARCH.md §1c).
 *
 * The two controls at the top are the whole question: *which name* and *as of
 * when*. Every panel below answers that one question, and re-answers it when
 * either control moves. The as-of date is not a filter over a fixed answer — it
 * changes what the answer is, because the same symbol on two dates is two
 * different sets of accounts, and the point of this screen is that a reader can
 * see that happen.
 */
export function CompanyView({ symbol, onSelectSymbol, asOf: asOfProp, onAsOfChange }: CompanyViewProps) {
  // Pinned at mount. Recomputing it per render would let the "Today" preset
  // drift mid-session and re-key every read at midnight.
  const [today] = useState(() => todayISO());
  // The date is the other half of the question, so it belongs in the address
  // bar beside the symbol -- a company worth bookmarking is a company *on a
  // date*, and a link that drops the date silently answers a different
  // question. Local state is the fallback for rendering outside the route.
  const [localAsOf, setLocalAsOf] = useState(today);
  const asOf = asOfProp ?? localAsOf;
  const setAsOf = onAsOfChange ?? setLocalAsOf;

  const instruments = useInstruments();
  const overview = useCompanyOverview(symbol, asOf);
  const prices = useCompanyPrices(symbol, asOf);

  // While `/overview` is being written it answers 404, and the accounts are
  // still reachable through the thin fundamentals route. The fallback fires
  // only when the composed route is unavailable, so a working backend is never
  // asked the same question twice — and it is the hook the strategies surface
  // already uses, not a second reader.
  const overviewMissing = overview.status === 'unsupported' || overview.status === 'error';
  const fallbackFacts = useInstrumentFacts(overviewMissing ? symbol : null, asOf);

  const company = overview.data;
  const catalogued = useMemo(
    () => instruments.data.find((instrument) => instrument.symbol === symbol) ?? null,
    [instruments.data, symbol],
  );

  const facts = company ? company.facts : fallbackFacts.facts;
  const factsStatus: ReadStatus = overviewMissing ? fallbackFacts.status : overview.status;
  const factsMessage = overviewMissing ? fallbackFacts.message : overview.message;
  const rows = useAsFiledRows(facts);

  const available = company?.concepts_available ?? [];
  const missing = company?.concepts_missing ?? [];
  const hasAnyFilings = overview.status === 'ready' ? available.length > 0 : null;
  const currency = company?.currency ?? catalogued?.currency ?? null;

  function reloadCompany() {
    overview.reload();
    prices.reload();
    fallbackFacts.reload();
  }

  return (
    <FillColumn className="gap-3 p-3">
      {/*
        No title here: the shell already names the mode and states its purpose
        directly above this, and two near-identical sentences stacked is exactly
        the kind of chrome this change removes. What the shell does *not* say is
        how the two controls relate, so that is what this line is for.
      */}
      <div className="shrink-0 border border-border bg-card p-3">
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          Two controls set the question: <span className="text-foreground">which name</span>, and{' '}
          <span className="text-foreground">as of when</span>. Everything below re-reads when either
          moves — the same company on two dates is two different answers.
        </p>
        <div className="flex flex-wrap items-start gap-3">
          <SymbolPicker
            instruments={instruments.data}
            status={instruments.status}
            message={instruments.message}
            selected={symbol}
            onSelect={onSelectSymbol}
          />
          <SymbolPickerRetry status={instruments.status} onRetry={instruments.reload} />
          <AsOfControl value={asOf} onChange={setAsOf} today={today} resolved={company?.as_of} />
        </div>
      </div>

      {symbol === null ? (
        <ScrollRegion>
          <EmptyState
            icon={Search}
            title="Pick a company to begin"
            detail="Type a ticker or part of a company name in the box above."
            testId="company-no-selection"
            className="my-10"
            action={
              <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
                You will get its price history, the accounts that were public on your chosen date
                with the filing date beside each figure, the rules that have fired on it, and an
                explicit list of what it has never filed.
              </p>
            }
          />
        </ScrollRegion>
      ) : (
        <ScrollRegion className="pr-1" testId="company-body">
          <Identity
            symbol={symbol}
            name={company?.name ?? catalogued?.name ?? null}
            exchange={company?.exchange ?? null}
            currency={currency}
            sector={company?.sector ?? ''}
            lastClose={company?.last_close ?? null}
            firstBar={company?.first_bar ?? null}
            lastBar={company?.last_bar ?? null}
            signalTotal={company?.signal_total ?? null}
            status={overview.status}
          />

          {/*
            Two columns from 1280px, one below it. The wider column carries the
            two things a reader looks at together — the price and the accounts
            underneath it — and the narrower one carries the two that qualify
            them.
          */}
          <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-3">
              <PricePanel
                symbol={symbol}
                asOf={asOf}
                bars={prices.data}
                status={prices.status}
                message={prices.message}
                currency={currency}
                onRetry={prices.reload}
              />
              <AsFiledPanel
                symbol={symbol}
                asOf={asOf}
                rows={rows}
                status={factsStatus}
                message={factsMessage}
                hasAnyFilings={hasAnyFilings}
                onRetry={reloadCompany}
              />
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              <SignalHistoryPanel
                symbol={symbol}
                signals={company?.signals ?? []}
                total={company?.signal_total ?? 0}
                status={overview.status}
                message={overview.message}
                onRetry={overview.reload}
              />
              <CoveragePanel
                symbol={symbol}
                available={available}
                missing={missing}
                status={overview.status}
                message={overview.message}
                onRetry={overview.reload}
              />
            </div>
          </div>
        </ScrollRegion>
      )}
    </FillColumn>
  );
}

/**
 * Who this is, in one strip.
 *
 * Deliberately above the panels and outside them: the symbol, the name and the
 * span of data available are the frame everything below is read inside, and a
 * reader who has just typed three letters needs to see immediately that they
 * landed on the company they meant.
 */
function Identity({
  symbol,
  name,
  exchange,
  currency,
  sector,
  lastClose,
  firstBar,
  lastBar,
  signalTotal,
  status,
}: {
  symbol: string;
  name: string | null;
  exchange: string | null;
  currency: string | null;
  sector: string;
  lastClose: number | null;
  firstBar: string | null;
  lastBar: string | null;
  signalTotal: number | null;
  status: ReadStatus;
}) {
  return (
    <div data-testid="company-identity" className="border border-border bg-card p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-base tabular-nums text-primary">{symbol}</span>
        <span className="font-display text-base font-medium text-foreground">
          {name ?? 'Name unavailable'}
        </span>
        {/* 607 of 644 names carry a blank sector, so it renders only when real. */}
        {sector ? <StatusBadge tone="idle">{sector}</StatusBadge> : null}
        {status === 'loading' ? (
          <StatusBadge tone="idle" role="status">
            Reading
          </StatusBadge>
        ) : null}
        {status === 'unsupported' ? (
          <StatusBadge tone="idle" title="This backend does not serve the company overview route.">
            Overview not served
          </StatusBadge>
        ) : null}
        {status === 'error' ? (
          <StatusBadge tone="bad" title="The company overview could not be read.">
            Overview unavailable
          </StatusBadge>
        ) : null}
      </div>
      <StatGrid className="mt-3" min="9rem" testId="company-identity-stats">
        <Stat label="Exchange" value={exchange || NOT_APPLICABLE} mono={false} />
        <Stat label="Currency" value={currency || NOT_APPLICABLE} />
        <Stat label="Last close" value={formatPrice(lastClose, currency ?? undefined)} />
        <Stat label="Bars from" value={firstBar ?? NOT_APPLICABLE} />
        <Stat label="Bars to" value={lastBar ?? NOT_APPLICABLE} />
        <Stat label="Signals" value={formatCount(signalTotal)} />
      </StatGrid>
    </div>
  );
}

function Stat({ label, value, mono = true }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <p className={mono ? 'mt-0.5 font-mono text-sm tabular-nums' : 'mt-0.5 text-sm'}>{value}</p>
    </div>
  );
}

export default CompanyView;

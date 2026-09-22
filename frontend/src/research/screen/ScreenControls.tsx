import { Plus, X } from 'lucide-react';
import type { ScreenMetric, ScreenMetricCoverage } from '../../api/types';
import { SCREEN_METRICS } from '../../api/types';
import { Button } from '../../components/ui/button';
import { fieldClasses } from '../../components/ui/field';
import { METRIC_FORMAT } from '../format';
import { CoverageLine } from './Coverage';
import { echoBound, isFraction, type ConstraintDraft, type DraftErrors } from './constraints';
import type { UniverseSummary } from './useScreen';

const LABEL = 'font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground';

export interface ScreenControlsProps {
  universes: UniverseSummary[];
  universe: string;
  onUniverse: (name: string) => void;
  asOf: string;
  onAsOf: (value: string) => void;
  limit: number;
  onLimit: (value: number) => void;
  drafts: ConstraintDraft[];
  errors: DraftErrors;
  onAddConstraint: () => void;
  onChangeConstraint: (id: string, patch: Partial<ConstraintDraft>) => void;
  onRemoveConstraint: (id: string) => void;
  /** Per-metric coverage from the last answer; null before the first run. */
  coverageFor: (metric: ScreenMetric) => ScreenMetricCoverage | null;
  onRun: () => void;
  running: boolean;
  blocked: boolean;
  /** True when the form has moved on from the result currently on screen. */
  stale: boolean;
}

/**
 * The question, assembled before it is asked.
 *
 * Nothing here fires a request. A screen is ~1s of index work over the whole
 * universe (docs/RESEARCH.md §2), and a form that ran on every keystroke would
 * paint four answers to questions the user was still in the middle of typing.
 * The Run button is the only thing that asks, and `stale` says plainly when
 * the table below no longer answers what is on this panel.
 */
export function ScreenControls(props: ScreenControlsProps) {
  const {
    universes,
    universe,
    onUniverse,
    asOf,
    onAsOf,
    limit,
    onLimit,
    drafts,
    errors,
    onAddConstraint,
    onChangeConstraint,
    onRemoveConstraint,
    coverageFor,
    onRun,
    running,
    blocked,
    stale,
  } = props;

  const chosen = universes.find((entry) => entry.name === universe) ?? null;

  return (
    <div className="space-y-5" data-testid="screen-controls">
      <div className="space-y-1.5">
        <label className={LABEL} htmlFor="screen-universe">
          Universe
        </label>
        <select
          id="screen-universe"
          className={fieldClasses}
          value={universe}
          onChange={(event) => onUniverse(event.target.value)}
        >
          {universes.map((entry) => (
            <option key={entry.name} value={entry.name}>
              {entry.name}
            </option>
          ))}
        </select>
        <p className="text-[11px] leading-snug text-muted-foreground">
          {chosen
            ? `${chosen.size.toLocaleString('en-US')} members, as the list stood on ${chosen.as_of}. A screen is always bounded by a list — that is how the filings index is keyed, and how the work is actually done.`
            : 'A screen is always bounded by a named list.'}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className={LABEL} htmlFor="screen-as-of">
            As filed on
          </label>
          <input
            id="screen-as-of"
            type="date"
            className={fieldClasses}
            value={asOf}
            onChange={(event) => onAsOf(event.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <label className={LABEL} htmlFor="screen-limit">
            Rows
          </label>
          <select
            id="screen-limit"
            className={fieldClasses}
            value={String(limit)}
            onChange={(event) => onLimit(Number(event.target.value))}
          >
            {[25, 50, 100, 200].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="-mt-3 text-[11px] leading-snug text-muted-foreground">
        Leave the date empty to use the most recent filings. Set one and every ratio is computed
        from the accounts that were public on that day — nothing filed later leaks in.
      </p>

      <div className="space-y-3 border-t border-border pt-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className={LABEL}>Constraints</span>
          <Button type="button" variant="ghost" size="sm" onClick={onAddConstraint}>
            <Plus size={16} strokeWidth={1.5} />
            Add
          </Button>
        </div>

        {drafts.length === 0 ? (
          <p className="text-[11px] leading-snug text-muted-foreground">
            No constraints. The screen returns the universe ranked, with every ratio shown and the
            holes in the filings left visible as dashes.
          </p>
        ) : null}

        {drafts.map((draft) => (
          <ConstraintRow
            key={draft.id}
            draft={draft}
            error={errors[draft.id] ?? null}
            coverage={coverageFor(draft.metric)}
            onChange={(patch) => onChangeConstraint(draft.id, patch)}
            onRemove={() => onRemoveConstraint(draft.id)}
          />
        ))}
      </div>

      <div className="space-y-2 border-t border-border pt-4">
        <Button
          type="button"
          onClick={onRun}
          disabled={blocked || running}
          className="w-full"
          data-testid="run-screen"
        >
          {running ? 'Screening…' : 'Run screen'}
        </Button>
        <p className="text-[11px] leading-snug text-muted-foreground" data-testid="screen-run-note">
          {running
            ? 'Reading the filings for every member of the universe. A few seconds.'
            : stale
              ? 'The table below answers the previous question. Run to apply these changes.'
              : 'A screen reads the whole universe, so it runs when you ask and not before.'}
        </p>
      </div>
    </div>
  );
}

function ConstraintRow({
  draft,
  error,
  coverage,
  onChange,
  onRemove,
}: {
  draft: ConstraintDraft;
  error: string | null;
  coverage: ScreenMetricCoverage | null;
  onChange: (patch: Partial<ConstraintDraft>) => void;
  onRemove: () => void;
}) {
  const format = METRIC_FORMAT[draft.metric];
  const minEcho = echoBound(draft.metric, draft.min);
  const maxEcho = echoBound(draft.metric, draft.max);

  return (
    <div
      data-testid={`constraint-${draft.metric}`}
      className="space-y-2 border border-border bg-background/40 p-2.5"
    >
      <div className="flex items-center gap-2">
        <select
          aria-label="Metric"
          className={`${fieldClasses} h-8`}
          value={draft.metric}
          onChange={(event) => onChange({ metric: event.target.value as ScreenMetric })}
        >
          {SCREEN_METRICS.map((metric) => (
            <option key={metric} value={metric}>
              {METRIC_FORMAT[metric].label}
            </option>
          ))}
        </select>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onRemove}
          aria-label={`Remove the ${format.label} constraint`}
        >
          <X size={16} strokeWidth={1.5} />
        </Button>
      </div>

      <p className="text-[11px] text-muted-foreground">{format.hint}</p>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1">
          <span className={LABEL}>Min</span>
          <input
            className={`${fieldClasses} h-8`}
            inputMode="decimal"
            placeholder="—"
            value={draft.min}
            onChange={(event) => onChange({ min: event.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={LABEL}>Max</span>
          <input
            className={`${fieldClasses} h-8`}
            inputMode="decimal"
            placeholder="—"
            value={draft.max}
            onChange={(event) => onChange({ max: event.target.value })}
          />
        </label>
      </div>

      {/*
        The unit, said out loud and echoed back. A margin is held as a
        fraction, so 0.12 is 12%; guessing that a typed `12` meant 12% and
        dividing it by 100 behind the user's back is the one failure worse
        than an unlabelled box.
      */}
      <p className="font-mono text-[10px] tabular-nums text-muted-foreground">
        {isFraction(draft.metric) ? 'a fraction — 0.12 is 12%' : 'a plain number'}
        {minEcho || maxEcho ? (
          <span className="ml-1.5 text-foreground">
            {minEcho ? `≥ ${minEcho}` : ''}
            {minEcho && maxEcho ? ' and ' : ''}
            {maxEcho ? `≤ ${maxEcho}` : ''}
          </span>
        ) : null}
      </p>

      <CoverageLine metric={draft.metric} coverage={coverage} />

      {error ? (
        <p role="alert" className="text-[11px] text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

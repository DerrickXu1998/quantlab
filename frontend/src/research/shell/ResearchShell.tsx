import type { ReactNode } from 'react';
import { Building2, FlaskConical, Filter, type LucideIcon } from 'lucide-react';
import { cn } from '../../lib/utils';
import { FillColumn } from '../../components/ui/layout';
import { RESEARCH_MODES, type ResearchMode } from './useResearchRoute';

/**
 * What each mode is, in one sentence, on the screen.
 *
 * This table is the direct answer to the reported complaint — *"the each
 * panels are not obvious what it means or what does it do"*. The old
 * destination named its panels after database tables (`signals`,
 * `signal_rules`, `experiment_runs`) and said nothing anywhere about what any
 * of them were for. A mode whose purpose is not written on the screen has
 * failed, so the sentence is not optional chrome: it renders beside the
 * switcher at all times, not in a tooltip and not behind a help icon.
 *
 * The sentences are in the second person and describe an action, because the
 * question being answered is "what do I do here", not "what is this called".
 */
interface ModeDefinition {
  id: ResearchMode;
  label: string;
  icon: LucideIcon;
  /** Shown under the switcher whenever this mode is active. */
  purpose: string;
}

export const MODE_DEFINITIONS: Record<ResearchMode, ModeDefinition> = {
  company: {
    id: 'company',
    label: 'Company',
    icon: Building2,
    purpose: 'Look up one name and see its price, its accounts as filed, and every signal it has fired.',
  },
  screen: {
    id: 'screen',
    label: 'Screen',
    icon: Filter,
    purpose: 'Narrow a universe by the ratios companies actually filed, then open any name.',
  },
  test: {
    id: 'test',
    label: 'Test',
    icon: FlaskConical,
    purpose: 'Run a rule over history and see what it would have done.',
  },
};

/**
 * The mode switcher.
 *
 * Deliberately not a dock, and not tabs that look like panel tabs. The
 * previous destination let the user float, drag and merge six panels, which
 * asked them to arrange tools they could not identify — a dock is the right
 * shape for a settled workflow and the wrong one for comprehension
 * (docs/RESEARCH.md §1d). Three labelled destinations with a stated purpose
 * replace it.
 */
function ModeSwitcher({
  mode,
  onChange,
}: {
  mode: ResearchMode;
  onChange: (mode: ResearchMode) => void;
}) {
  return (
    <div role="tablist" aria-label="Research mode" className="flex items-center gap-1">
      {RESEARCH_MODES.map((id) => {
        const definition = MODE_DEFINITIONS[id];
        const Icon = definition.icon;
        const active = id === mode;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`research-panel-${id}`}
            id={`research-tab-${id}`}
            onClick={() => onChange(id)}
            className={cn(
              'inline-flex items-center gap-2 rounded-sm border px-3 py-1.5',
              'font-mono text-[11px] uppercase tracking-[0.12em] transition-colors',
              'focus-visible:outline-none focus-visible:border-primary',
              active
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground',
            )}
          >
            <Icon size={16} strokeWidth={1.5} aria-hidden />
            {definition.label}
          </button>
        );
      })}
    </div>
  );
}

export interface ResearchShellProps {
  mode: ResearchMode;
  onModeChange: (mode: ResearchMode) => void;
  /** Rendered to the right of the switcher — the active mode's own controls. */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * The Research destination's frame: a header that says what this is, and one
 * region for the active mode.
 *
 * One mode is mounted at a time. The old destination kept all six panels
 * mounted because Dockview corrupts its layout when measured at 0x0, and that
 * constraint dies with the dock — so an inactive mode costs nothing and a
 * heavy screen result is not held alive behind a tab nobody is looking at.
 */
export function ResearchShell({ mode, onModeChange, actions, children }: ResearchShellProps) {
  const definition = MODE_DEFINITIONS[mode];

  return (
    <FillColumn className="h-full">
      <header className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4">
            <h1 className="font-display text-sm uppercase tracking-[0.18em] text-muted-foreground">
              Research
            </h1>
            <ModeSwitcher mode={mode} onChange={onModeChange} />
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{definition.purpose}</p>
      </header>

      {/* A flex column, not a plain block.
          Each mode's root is a `FillColumn`, whose `flex-1` is inert unless
          its parent is itself a flex container — so as a block this region
          handed every mode its natural height and the whole destination
          scrolled the page instead of filling the viewport: 1,838px of
          document against a 900px window, with the accounts below the fold.
          `min-h-0` is what lets it shrink far enough for the regions inside
          to become the scroll edge. */}
      <div
        role="tabpanel"
        id={`research-panel-${mode}`}
        aria-labelledby={`research-tab-${mode}`}
        className="flex min-h-0 flex-1 flex-col"
      >
        {children}
      </div>
    </FillColumn>
  );
}

/**
 * A titled region inside a mode.
 *
 * The one place a panel title is allowed to be set, and it cannot be set
 * without `purpose`. That is the constraint doing the work: the previous
 * destination's panels were titled `Filters`, `Signals`, `Models` with nothing
 * else, and making the explanation a required argument is what stops that
 * recurring the next time somebody adds a panel in a hurry.
 */
export function ResearchPanel({
  title,
  purpose,
  actions,
  children,
  className,
  icon: Icon,
}: {
  title: string;
  purpose: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  icon?: LucideIcon;
}) {
  return (
    <section className={cn('flex min-h-0 flex-col border border-border bg-card', className)}>
      <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-3 py-2">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-display text-xs uppercase tracking-[0.14em]">
            {Icon ? <Icon size={16} strokeWidth={1.5} className="text-muted-foreground" /> : null}
            {title}
          </h2>
          <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{purpose}</p>
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}

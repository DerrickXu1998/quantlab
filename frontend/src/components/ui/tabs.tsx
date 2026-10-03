import type { LucideIcon } from 'lucide-react';
import type { KeyboardEvent, ReactNode } from 'react';
import { cn } from '../../lib/utils';

export interface TabItem<T extends string> {
  id: T;
  label: string;
  icon?: LucideIcon;
  /** A count shown after the label (active runs on Runs). Hidden when 0 or absent. */
  badge?: number;
  /** Spoken with the label: "Runs, 2 active". */
  badgeLabel?: string;
}

/**
 * A row of tabs: one destination's sub-views (Research's modes, Strategies'
 * Configure and Runs).
 *
 * WAI-ARIA tabs with a roving tab index: Tab enters the row on the selected
 * tab, the arrow keys (and Home/End) move between tabs and select as they go.
 * `idPrefix` pairs each tab with its panel: the panel is `${idPrefix}-panel-${id}`
 * and should carry `role="tabpanel"` and `aria-labelledby={tabId(idPrefix, id)}`.
 */
export function TabBar<T extends string>({
  items,
  value,
  onChange,
  label,
  idPrefix,
  className,
}: {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  idPrefix: string;
  className?: string;
}) {
  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = items.length - 1;
    const next =
      event.key === 'ArrowRight'
        ? index === last
          ? 0
          : index + 1
        : event.key === 'ArrowLeft'
          ? index === 0
            ? last
            : index - 1
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? last
              : null;
    if (next === null) return;
    event.preventDefault();
    const target = items[next];
    if (!target) return;
    onChange(target.id);
    document.getElementById(tabId(idPrefix, target.id))?.focus();
  };

  return (
    <div role="tablist" aria-label={label} className={cn('flex flex-wrap items-center gap-1', className)}>
      {items.map((item, index) => {
        const Icon = item.icon;
        const active = item.id === value;
        const badge = item.badge && item.badge > 0 ? item.badge : null;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`${idPrefix}-panel-${item.id}`}
            aria-label={badge && item.badgeLabel ? `${item.label}, ${item.badgeLabel}` : undefined}
            id={tabId(idPrefix, item.id)}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => move(event, index)}
            className={cn(
              // 44px of target on a phone, the original dense row at `lg`.
              'inline-flex h-11 items-center gap-2 rounded-sm border px-3 lg:h-auto lg:py-1.5',
              'font-mono text-[11px] uppercase tracking-[0.12em] transition-colors',
              'focus-visible:outline-none focus-visible:border-primary',
              active
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground',
            )}
          >
            {Icon ? <Icon size={16} strokeWidth={1.5} aria-hidden /> : null}
            {item.label}
            {badge ? <TabCount active={active}>{badge}</TabCount> : null}
          </button>
        );
      })}
    </div>
  );
}

function TabCount({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <span
      data-testid="tab-count"
      className={cn(
        'rounded-sm border px-1 tabular-nums tracking-normal',
        active ? 'border-primary-foreground/40' : 'border-primary/50 text-primary',
      )}
    >
      {children}
    </span>
  );
}

export function tabId(idPrefix: string, id: string): string {
  return `${idPrefix}-tab-${id}`;
}

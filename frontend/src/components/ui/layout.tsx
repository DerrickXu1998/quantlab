import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

/**
 * The layout primitives this surface was missing.
 *
 * Four fitting faults kept recurring across the destinations, each fixed ad hoc
 * where somebody noticed it and left alone everywhere else:
 *
 *   1. panels took their natural height and left the bottom of the workspace
 *      empty — 380px of dead ground on Market, 290px on Replay;
 *   2. tables ran past their container and were clipped *mid-row*, so the last
 *      thing on screen was half a number;
 *   3. rows in a very wide container pinned their first and last cell to the
 *      extreme edges, stranding the content with a metre of nothing between;
 *   4. segmented controls wrapped one item onto a second line.
 *
 * They are all the same class of mistake — a container that does not say what
 * it wants — so they are fixed once, here, and the destinations compose these
 * instead of re-deriving the flexbox each time.
 *
 * Every one of these is a plain wrapper with no state. They exist to make the
 * right thing the short thing to type.
 */

/**
 * A column that fills its parent and lets exactly one child grow.
 *
 * `min-h-0` is the part everyone forgets: without it a flex child refuses to
 * shrink below its content, the overflow escapes the box instead of scrolling
 * inside it, and the clipping in fault 2 is the result.
 */
export function FillColumn({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn('flex min-h-0 flex-1 flex-col', className)}>{children}</div>;
}

/**
 * The scrolling part of a panel.
 *
 * A region that scrolls rather than a box that clips. Anything tall enough to
 * overflow — an order book, a signal table, a trade log — belongs in one of
 * these, so the boundary is a scroll edge the user can act on instead of a
 * row sliced through the middle.
 */
export function ScrollRegion({
  children,
  className,
  testId,
}: {
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <div data-testid={testId} className={cn('min-h-0 flex-1 overflow-y-auto', className)}>
      {children}
    </div>
  );
}

/**
 * Content with a reading measure, centred in whatever space it is given.
 *
 * The fix for fault 3. An order book is about 32 characters wide; give it
 * 1120px and `justify-between` will put the price on one side of the screen
 * and the size on the other. Capping the measure and centring keeps a row
 * scannable in one fixation, and lets the panel be as wide as the grid wants
 * without the data spreading to fill it.
 *
 * Widths are deliberately coarse. A per-panel pixel value is how a design
 * system turns back into a pile of magic numbers.
 */
const MEASURE = {
  /** A dense two- or three-column readout: an order book, a stat pair. */
  narrow: 'max-w-[34rem]',
  /** A table with four to six columns. */
  base: 'max-w-[56rem]',
  /** A wide table, or prose that should still not run to 1600px. */
  wide: 'max-w-[80rem]',
} as const;

export function Measure({
  children,
  size = 'base',
  className,
  center = true,
}: {
  children: ReactNode;
  size?: keyof typeof MEASURE;
  className?: string;
  center?: boolean;
}) {
  return (
    <div className={cn('w-full', MEASURE[size], center && 'mx-auto', className)}>{children}</div>
  );
}

/**
 * A row of labelled figures that stays legible at any width.
 *
 * `auto-fit` with a minimum column, rather than a fixed column count: five
 * stats across 1100px were landing one per 220px with the label orphaned from
 * its number. This packs them at a readable density and wraps to a second row
 * instead of stretching.
 */
export function StatGrid({
  children,
  className,
  min = '11rem',
  testId,
}: {
  children: ReactNode;
  className?: string;
  /** Narrowest a column may get before the grid wraps. */
  min?: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className={cn('grid gap-x-8 gap-y-4', className)}
      style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${min}, max-content))` }}
    >
      {children}
    </div>
  );
}

/**
 * A segmented control that wraps as a block rather than orphaning its last item.
 *
 * The replay speed picker was breaking `FAST | 25 MS | 50 MS` across one line
 * and `100 MS` onto the next, which reads as two controls. This keeps the set
 * together and lets it wrap as a unit when it genuinely cannot fit.
 */
export function ButtonGroup({
  children,
  className,
  label,
  title,
}: {
  children: ReactNode;
  className?: string;
  /** Names the set for a screen reader; the buttons inside carry the state. */
  label?: string;
  /**
   * Hover text for the set.
   *
   * On the group rather than a wrapping fieldset, so the tooltip's target is
   * the control it describes and not the whole legend-and-label block around
   * it.
   */
  title?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      title={title}
      className={cn('flex flex-wrap items-center gap-1', className)}
    >
      {children}
    </div>
  );
}

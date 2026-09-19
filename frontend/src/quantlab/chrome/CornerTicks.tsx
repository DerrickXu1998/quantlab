/**
 * Four L-marks at the corners of a panel. Terminal chrome: it reads as a
 * machined edge rather than a card, which is what keeps the surface from
 * looking like a dashboard.
 */
export function CornerTicks() {
  const arm = 'absolute h-px w-2 bg-border';
  const armV = 'absolute h-2 w-px bg-border';
  return (
    <span aria-hidden="true" className="pointer-events-none absolute inset-0">
      <span className={`${arm} left-0 top-0`} />
      <span className={`${armV} left-0 top-0`} />
      <span className={`${arm} right-0 top-0`} />
      <span className={`${armV} right-0 top-0`} />
      <span className={`${arm} bottom-0 left-0`} />
      <span className={`${armV} bottom-0 left-0`} />
      <span className={`${arm} bottom-0 right-0`} />
      <span className={`${armV} bottom-0 right-0`} />
    </span>
  );
}

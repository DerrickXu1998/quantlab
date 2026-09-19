/**
 * Film grain over the background at 3%.
 *
 * Fixed, non-interactive, and behind everything: at full-surface size it would
 * otherwise swallow every click on the page. `pointer-events-none` is set as a
 * utility here as well as in the CSS rule, so the guarantee is visible in the
 * markup and assertable without a stylesheet.
 */
export function GrainOverlay() {
  return (
    <div
      aria-hidden="true"
      className="quantlab-grain pointer-events-none fixed inset-0 z-0"
    />
  );
}

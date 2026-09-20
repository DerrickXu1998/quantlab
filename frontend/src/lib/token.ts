/**
 * Read a CSS custom property as a usable colour.
 *
 * Canvas and chart libraries cannot resolve `hsl(var(--x))`, so the tokens are
 * read off the live element instead of being duplicated as hex anywhere. That
 * is what stops chart code drifting out of step with the palette — and what
 * makes a theme switch free, since the values are re-read on the redraw.
 */
export function token(element: Element | null, name: string, alpha = 1): string {
  if (!element) return `hsla(0, 0%, 50%, ${alpha})`;
  const triplet = getComputedStyle(element).getPropertyValue(name).trim();
  if (!triplet) return `hsla(0, 0%, 50%, ${alpha})`;
  return `hsl(${triplet} / ${alpha})`;
}

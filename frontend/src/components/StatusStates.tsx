// `state`/`state-*` are stable identity hooks (tests and callers address these
// states by them); the Tailwind utilities alongside carry the styling.
const baseState = 'state my-4 rounded-lg border px-6 py-8 text-center text-sm';

export function Loading() {
  return (
    <div
      className={`${baseState} state-loading border-primary/30 bg-primary/10 text-primary`}
      role="status"
    >
      Loading signals…
    </div>
  );
}

export function EmptyResults() {
  return (
    <div
      className={`${baseState} state-empty border-border bg-muted text-muted-foreground`}
      data-testid="empty-results"
    >
      No signals match the current filters.
    </div>
  );
}

export function BackendUnavailable({ message }: { message?: string }) {
  return (
    <div
      className={`${baseState} state-error border-destructive/40 bg-destructive/10 text-destructive`}
      role="alert"
      data-testid="backend-unavailable"
    >
      <strong>Backend unavailable.</strong> The signal service could not be reached
      {message ? `: ${message}` : '.'} Start the stack and reload this page.
    </div>
  );
}

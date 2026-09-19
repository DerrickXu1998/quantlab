export function Loading() {
  return (
    <div className="state state-loading" role="status">
      Loading signals…
    </div>
  );
}

export function EmptyResults() {
  return (
    <div className="state state-empty" data-testid="empty-results">
      No signals match the current filters.
    </div>
  );
}

export function BackendUnavailable({ message }: { message?: string }) {
  return (
    <div className="state state-error" role="alert" data-testid="backend-unavailable">
      <strong>Backend unavailable.</strong> The signal service could not be reached
      {message ? `: ${message}` : '.'} Start the stack and reload this page.
    </div>
  );
}

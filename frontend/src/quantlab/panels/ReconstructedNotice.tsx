/**
 * Says a run's figures were rebuilt later rather than recorded as it ran.
 *
 * A run that predates stored results (or whose recording failed) is
 * re-executed once on the data as it then stood. Bars are revised and splits
 * restated, so those figures may differ from what the run did; the server
 * marks them `reconstructed`, and this says so wherever they are shown.
 */
export function ReconstructedNotice({ reconstructed }: { reconstructed?: boolean | null }) {
  if (!reconstructed) return null;
  return (
    <p data-testid="performance-reconstructed" className="text-xs text-muted-foreground">
      Rebuilt: these results were re-executed once on the data available later, not recorded
      as the run completed. They may differ from what the run did.
    </p>
  );
}

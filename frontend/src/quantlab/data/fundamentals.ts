import type { components } from '../../api/schema';
import { apiGet } from '../../lib/apiRequest';

/**
 * The fundamentals endpoints (feature 008): a per-instrument concept catalog
 * and point-in-time series over it. Lives here rather than in api/client
 * because that directory is regenerated; the shapes are still read off the
 * generated schema, so a contract drift fails typecheck.
 */

export type FundamentalConcept = components['schemas']['FundamentalConcept'];
export type FundamentalConceptList = components['schemas']['FundamentalConceptList'];
export type FundamentalSeries = components['schemas']['FundamentalSeries'];
export type FundamentalSeriesPoint = components['schemas']['FundamentalSeriesPoint'];
export type FundamentalFact = components['schemas']['FundamentalFact'];
export type FundamentalTransform = FundamentalSeries['transform'];

export function listFundamentalConcepts(symbol: string): Promise<FundamentalConceptList> {
  return apiGet<FundamentalConceptList>(
    `/instruments/${encodeURIComponent(symbol)}/fundamentals/concepts`,
  );
}

export function getFundamentalSeries(
  symbol: string,
  concept: string,
  transform: FundamentalTransform = 'raw',
): Promise<FundamentalSeries> {
  return apiGet<FundamentalSeries>(
    `/instruments/${encodeURIComponent(symbol)}/fundamentals/series`,
    { concept, transform },
  );
}

/** Series items are the union of as-of points and filing rows; the visibility
 *  anchor (`filed_at`) is what tells them apart. */
export function isFact(item: FundamentalSeriesPoint | FundamentalFact): item is FundamentalFact {
  return 'filed_at' in item;
}

export function isSeriesPoint(
  item: FundamentalSeriesPoint | FundamentalFact,
): item is FundamentalSeriesPoint {
  return !isFact(item);
}

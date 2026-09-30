import { useCallback, useSyncExternalStore } from 'react';
import {
  createRun,
  getRun,
  getRunPerformance,
  getRunStudies,
  type ExperimentSignal,
  type Study,
} from '../../api/client';
import type { CatalogModel, ExecutionConfig, RunPerformanceV2 } from '../../api/types';
import { DEFAULT_EXECUTION } from '../../api/types';

/**
 * The execution assumptions the Models panel exposes: where a signal fills and
 * what it costs. Everything else about execution stays at the engine default --
 * one ticker, all in, no stops -- because this panel asks "does the model read
 * this stock", not "how should I size it", which is the Strategies builder's.
 */
export type ExecutionChoice = Pick<ExecutionConfig, 'fill_timing' | 'commission_bps' | 'slippage_bps'>;

export const DEFAULT_EXECUTION_CHOICE: ExecutionChoice = {
  fill_timing: DEFAULT_EXECUTION.fill_timing,
  commission_bps: DEFAULT_EXECUTION.commission_bps,
  slippage_bps: DEFAULT_EXECUTION.slippage_bps,
};

/** One model applied to the ticker on screen. */
export interface ModelOverlay {
  /** Local key; a model can be applied twice with different parameters. */
  key: string;
  model: CatalogModel;
  /** The overrides sent, for the label: `fast=10, slow=30`. */
  parameters: Record<string, unknown>;
  /** Where it filled and what it paid: the return below depends on both. */
  execution: ExecutionChoice;
  status: 'running' | 'ready' | 'error';
  error: string | null;
  runId: string | null;
  signals: ExperimentSignal[];
  performance: RunPerformanceV2 | null;
  /** The lines the model compared, drawn under its markers. Empty for RSI. */
  studies: Study[];
  visible: boolean;
}

export interface ApplyRequest {
  model: CatalogModel;
  parameters: Record<string, unknown>;
  execution?: ExecutionChoice;
  symbol: string;
  start: string;
  end: string;
}

let nextKey = 0;

/**
 * Applied overlays, kept per ticker and window across unmounts.
 *
 * The shell mounts one destination at a time, so overlays held in component
 * state were lost on every trip to another tab -- and a run still going when
 * the reader left had nowhere to land. Held here, a return finds them as they
 * were, and a result lands in the bucket of the ticker and window it was run
 * for, whatever is on screen by then. Bounded: a performance payload carries a
 * whole equity curve.
 */
const overlayStore = new Map<string, ModelOverlay[]>();
const OVERLAY_SCOPES_KEPT = 12;
const listeners = new Set<() => void>();
const NO_OVERLAYS: ModelOverlay[] = [];

function readOverlays(bucket: string): ModelOverlay[] {
  return overlayStore.get(bucket) ?? NO_OVERLAYS;
}

function writeOverlays(bucket: string, change: (current: ModelOverlay[]) => ModelOverlay[]) {
  const next = change(readOverlays(bucket));
  overlayStore.delete(bucket);
  if (next.length > 0) overlayStore.set(bucket, next);
  while (overlayStore.size > OVERLAY_SCOPES_KEPT) {
    const oldest = overlayStore.keys().next().value;
    if (oldest === undefined) break;
    overlayStore.delete(oldest);
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** For tests: each starts with nothing applied anywhere. */
export function clearOverlayStore() {
  overlayStore.clear();
  for (const listener of listeners) listener();
}

/**
 * Models applied to one ticker, each a real run over that ticker's history.
 *
 * A run rather than anything computed here: the signals on the chart have to
 * be the engine's own, point-in-time and with the same warm-up and parameters a
 * strategy would get, or the chart would be showing a different model from the
 * one that trades (Constitution V). Each overlay is therefore replayable and
 * listed with every other run.
 *
 * Overlays belong to the ticker and the window: changing either shows that
 * pair's own overlays, because markers from one name drawn on another's chart
 * are simply wrong. Coming back to a pair -- or to the tab -- shows them again.
 */
export function useModelOverlays(
  symbol: string | null,
  onRunCreated?: () => void,
  /**
   * The window on screen, e.g. `2025-09-30..2026-09-30`. Overlays belong to it
   * as they belong to the ticker: a return measured over ten years printed
   * under a one-year chart is a number about something that is not shown.
   */
  scope: string = '',
) {
  const bucket = `${symbol ?? ''}|${scope}`;
  const overlays = useSyncExternalStore(
    subscribe,
    () => readOverlays(bucket),
    () => readOverlays(bucket),
  );

  const apply = useCallback(
    async ({
      model,
      parameters,
      execution = DEFAULT_EXECUTION_CHOICE,
      symbol: subject,
      start,
      end,
    }: ApplyRequest) => {
      const key = `overlay-${(nextKey += 1)}`;
      // Captured now: the result belongs to this pair even if the reader has
      // moved to another ticker, window or tab by the time it lands.
      const home = bucket;
      const patch = (change: Partial<ModelOverlay>) =>
        writeOverlays(home, (current) =>
          current.map((o) => (o.key === key ? { ...o, ...change } : o)),
        );
      writeOverlays(home, (current) => [
        ...current,
        {
          key,
          model,
          parameters,
          execution,
          status: 'running',
          error: null,
          runId: null,
          signals: [],
          performance: null,
          studies: [],
          visible: true,
        },
      ]);
      try {
        const run = await createRun({
          model_name: model.name,
          parameters,
          symbols: [subject],
          start_date: start,
          end_date: end,
          execution: { ...DEFAULT_EXECUTION, ...execution },
        });
        onRunCreated?.();
        if (run.status !== 'completed') {
          throw new Error(run.error ?? `the run ended as ${run.status}`);
        }
        const [detail, performance, studies] = await Promise.all([
          getRun(run.id),
          getRunPerformance(run.id),
          getRunStudies(run.id, subject),
        ]);
        patch({
          status: 'ready',
          runId: run.id,
          signals: detail.signals.filter((signal) => signal.symbol === subject),
          performance,
          studies: studies.studies,
        });
      } catch (caught: unknown) {
        patch({
          status: 'error',
          error: caught instanceof Error ? caught.message : 'the model could not be run',
        });
      }
    },
    [bucket, onRunCreated],
  );

  const toggle = useCallback(
    (key: string) =>
      writeOverlays(bucket, (current) =>
        current.map((o) => (o.key === key ? { ...o, visible: !o.visible } : o)),
      ),
    [bucket],
  );

  const remove = useCallback(
    (key: string) => writeOverlays(bucket, (current) => current.filter((o) => o.key !== key)),
    [bucket],
  );

  return { overlays, apply, toggle, remove };
}

/** The short label drawn on the chart beside each marker: `sma-crossover` → `SMA`. */
export function markerLabel(modelName: string): string {
  return modelName.split('-')[0].toUpperCase();
}

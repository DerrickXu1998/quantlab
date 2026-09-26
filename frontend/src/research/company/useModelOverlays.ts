import { useCallback, useEffect, useRef, useState } from 'react';
import { createRun, getRun, getRunPerformance, type ExperimentSignal } from '../../api/client';
import type { CatalogModel, RunPerformanceV2 } from '../../api/types';

/** One model applied to the ticker on screen. */
export interface ModelOverlay {
  /** Local key; a model can be applied twice with different parameters. */
  key: string;
  model: CatalogModel;
  /** The overrides sent, for the label: `fast=10, slow=30`. */
  parameters: Record<string, unknown>;
  status: 'running' | 'ready' | 'error';
  error: string | null;
  runId: string | null;
  signals: ExperimentSignal[];
  performance: RunPerformanceV2 | null;
  visible: boolean;
}

export interface ApplyRequest {
  model: CatalogModel;
  parameters: Record<string, unknown>;
  symbol: string;
  start: string;
  end: string;
}

let nextKey = 0;

/**
 * Models applied to one ticker, each a real run over that ticker's history.
 *
 * A run rather than anything computed here: the signals on the chart have to
 * be the engine's own, point-in-time and with the same warm-up and parameters a
 * strategy would get, or the chart would be showing a different model from the
 * one that trades (Constitution V). Each overlay is therefore replayable and
 * listed with every other run.
 *
 * Overlays belong to the ticker: picking another one clears them, because
 * markers from one name drawn on another's chart are simply wrong.
 */
export function useModelOverlays(symbol: string | null, onRunCreated?: () => void) {
  const [overlays, setOverlays] = useState<ModelOverlay[]>([]);
  // Results that land after the ticker changed must not be applied to the new one.
  const generation = useRef(0);

  useEffect(() => {
    generation.current += 1;
    setOverlays([]);
  }, [symbol]);

  const patch = useCallback((key: string, change: Partial<ModelOverlay>) => {
    setOverlays((current) => current.map((o) => (o.key === key ? { ...o, ...change } : o)));
  }, []);

  const apply = useCallback(
    async ({ model, parameters, symbol: subject, start, end }: ApplyRequest) => {
      const key = `overlay-${(nextKey += 1)}`;
      const mine = generation.current;
      setOverlays((current) => [
        ...current,
        {
          key,
          model,
          parameters,
          status: 'running',
          error: null,
          runId: null,
          signals: [],
          performance: null,
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
        });
        onRunCreated?.();
        if (run.status !== 'completed') {
          throw new Error(run.error ?? `the run ended as ${run.status}`);
        }
        const [detail, performance] = await Promise.all([
          getRun(run.id),
          getRunPerformance(run.id),
        ]);
        if (generation.current !== mine) return;
        patch(key, {
          status: 'ready',
          runId: run.id,
          signals: detail.signals.filter((signal) => signal.symbol === subject),
          performance,
        });
      } catch (caught: unknown) {
        if (generation.current !== mine) return;
        patch(key, {
          status: 'error',
          error: caught instanceof Error ? caught.message : 'the model could not be run',
        });
      }
    },
    [onRunCreated, patch],
  );

  const toggle = useCallback((key: string) => {
    setOverlays((current) =>
      current.map((o) => (o.key === key ? { ...o, visible: !o.visible } : o)),
    );
  }, []);

  const remove = useCallback((key: string) => {
    setOverlays((current) => current.filter((o) => o.key !== key));
  }, []);

  return { overlays, apply, toggle, remove };
}

/** The short label drawn on the chart beside each marker: `sma-crossover` → `SMA`. */
export function markerLabel(modelName: string): string {
  return modelName.split('-')[0].toUpperCase();
}

import { FlaskConical, Hourglass, PackageOpen, ServerCrash, SlidersHorizontal } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useRoute } from '../../chrome/router';
import { ModelList } from '../../components/ModelList';
import { RunConfigForm } from '../../components/RunConfigForm';
import { RunResultsView } from '../../components/RunResultsView';
import { Button } from '../../components/ui/button';
import { CascadeItem } from '../chrome/Cascade';
import { EmptyState } from '../chrome/EmptyState';
import { Panel } from '../chrome/Panel';
import { RuleBuilder } from '../panels/RuleBuilder';
import { useRuns } from '../../runs/RunsContext';
import type { CustomRule } from '../data/customRules';
import type { Instrument, Model } from '../../api/client';

/**
 * The first thing a new researcher sees in the middle column: what a strategy
 * run is, and the four steps to their first result. The form it points at is
 * already on screen in the right column, ready to use.
 */
function StrategyIntro({ model }: { model: Model }) {
  return (
    <div data-testid="strategy-intro" className="max-w-md space-y-4 px-1 py-6">
      <div className="space-y-2">
        <h3 className="font-display text-sm tracking-[-0.02em]">What a strategy run is</h3>
        <p className="text-xs leading-relaxed text-muted-foreground">
          {model.name} fires signals on stored daily bars. A strategy run replays those signals
          through your execution criteria — capital, sizing, costs, stops — and reports what the
          simulated fills would have done. Nothing here trades; the assumptions shipped with every
          result disclose exactly what was simplified.
        </p>
      </div>
      <ol className="space-y-1.5 text-xs text-muted-foreground">
        <li className="flex gap-2">
          <span className="font-mono text-[10px] text-foreground">01</span>
          Choose instruments and a date window.
        </li>
        <li className="flex gap-2">
          <span className="font-mono text-[10px] text-foreground">02</span>
          Tune the signal parameters.
        </li>
        <li className="flex gap-2">
          <span className="font-mono text-[10px] text-foreground">03</span>
          Set execution criteria, or keep the defaults.
        </li>
        <li className="flex gap-2">
          <span className="font-mono text-[10px] text-foreground">04</span>
          Run strategy — results appear here.
        </li>
      </ol>
    </div>
  );
}

/**
 * Strategies: the signal-strategy registry on the left, the result of the
 * current run in the middle, the configuration form on the right.
 *
 * The run state is the app's shared store, not local state — a run created in
 * Research is already selected here, and a "Re-run this model" handoff from a
 * signal row lands as a prefilled form (`?model=…&p_<param>=…`).
 */
export function StrategyLabView({ instruments }: { instruments: Instrument[] }) {
  const {
    modelEntries,
    modelsStatus,
    reloadModels,
    selectedModel,
    selectModel,
    customRules,
    removeRule,
    activeRun,
    inFlight,
    runError,
    start,
    cancel,
  } = useRuns();
  const route = useRoute();
  // The builder swaps in for the run form: null shows the form, `{rule:null}`
  // builds a new rule, `{rule}` edits one.
  const [builder, setBuilder] = useState<{ rule: CustomRule | null } | null>(null);
  // A saved rule is selected once the catalog reload picks it up.
  const [pendingRuleId, setPendingRuleId] = useState<string | null>(null);

  // The signal-row handoff: pick the named model once the registry has loaded.
  const modelParam = route.params.get('model');
  useEffect(() => {
    if (modelsStatus !== 'ready' || !modelParam) return;
    const match = modelEntries.find((entry) => entry.model.name === modelParam);
    if (match) selectModel(match.model);
    // modelEntries is derived from the same load; depending on the name keeps
    // this from re-firing on every unrelated store update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelsStatus, modelParam, modelEntries.length]);

  // The custom-rule equivalent of the handoff: `?rule=<custom_rule_id>`.
  const ruleParam = route.params.get('rule');
  useEffect(() => {
    if (modelsStatus !== 'ready' || !ruleParam) return;
    const match = modelEntries.find((entry) => entry.model.custom_rule_id === ruleParam);
    if (match) selectModel(match.model);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelsStatus, ruleParam, modelEntries.length]);

  useEffect(() => {
    if (modelsStatus !== 'ready' || !pendingRuleId) return;
    const match = modelEntries.find((entry) => entry.model.custom_rule_id === pendingRuleId);
    if (match) {
      selectModel(match.model);
      setPendingRuleId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelsStatus, pendingRuleId, modelEntries.length]);

  // Parameter prefill from the handoff: `p_<name>=<value>` pairs. Memoised on
  // the raw query string so the form does not re-seed on every render.
  const query = route.params.toString();
  const initialValues = useMemo(() => {
    const params = new URLSearchParams(query);
    const prefill: Record<string, string> = {};
    for (const [key, value] of params) {
      if (key.startsWith('p_')) prefill[key.slice(2)] = value;
    }
    return prefill;
  }, [query]);

  if (modelsStatus === 'error') {
    return (
      <EmptyState
        testId="strategies-error"
        icon={ServerCrash}
        tone="error"
        title="Backend unreachable"
        detail="The model registry could not be loaded."
        action={
          <Button type="button" variant="outline" size="sm" onClick={reloadModels}>
            Retry
          </Button>
        }
      />
    );
  }

  const registryEmpty = modelsStatus === 'ready' && modelEntries.length === 0;

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[240px_minmax(0,1fr)_320px]">
      <CascadeItem index={0} className="border-b border-border lg:border-b-0 lg:border-r">
        <Panel
          title="Signal strategies"
          className="border-0"
          bodyClassName="p-0"
          actions={
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setBuilder({ rule: null })}
            >
              New rule
            </Button>
          }
        >
          {modelsStatus === 'loading' ? (
            <EmptyState icon={Hourglass} title="Loading…" role="status" />
          ) : (
            <ModelList
              entries={modelEntries}
              selected={selectedModel?.name ?? null}
              onSelect={(name) => {
                setBuilder(null);
                selectModel(modelEntries.find((entry) => entry.model.name === name)?.model ?? null);
              }}
              rules={customRules}
              ruleActions={{
                onEdit: (rule) => setBuilder({ rule }),
                onDelete: (rule) => removeRule(rule.rule_id),
              }}
            />
          )}
        </Panel>
      </CascadeItem>

      <CascadeItem index={1} className="min-w-0 p-4">
        {selectedModel ? (
          <Panel
            title={`${selectedModel.name} — strategy run`}
            className="border-0"
            bodyClassName="p-0 pt-4"
            actions={
              <span className="font-mono text-[10px] text-muted-foreground">
                {selectedModel.direction_semantics}
              </span>
            }
          >
            {runError ? (
              <EmptyState
                testId="lab-run-error"
                icon={ServerCrash}
                tone="error"
                title="Strategy run could not start"
                detail={runError}
              />
            ) : activeRun ? (
              <RunResultsView run={activeRun} />
            ) : inFlight ? (
              <EmptyState icon={Hourglass} title="Running…" role="status" />
            ) : (
              <StrategyIntro model={selectedModel} />
            )}
          </Panel>
        ) : modelsStatus === 'loading' ? (
          <EmptyState icon={Hourglass} title="Loading…" role="status" />
        ) : registryEmpty ? (
          <EmptyState
            testId="lab-no-strategies"
            icon={PackageOpen}
            title="No strategies to run"
            detail="The signal registry is empty. Register a signal rule in the backend and it becomes runnable here without a frontend change."
          />
        ) : (
          <EmptyState
            icon={FlaskConical}
            title="Select a strategy"
            detail="Pick a signal strategy on the left to configure a run."
          />
        )}
      </CascadeItem>

      <CascadeItem index={2} className="border-t border-border p-4 lg:border-l lg:border-t-0">
        {builder ? (
          <Panel
            title={builder.rule ? `Edit rule — ${builder.rule.name}` : 'New custom rule'}
            className="border-0"
            bodyClassName="p-0 pt-4"
          >
            <RuleBuilder
              rule={builder.rule}
              onClose={() => setBuilder(null)}
              onSaved={(saved) => {
                setBuilder(null);
                setPendingRuleId(saved.rule_id);
                reloadModels();
              }}
            />
          </Panel>
        ) : selectedModel ? (
          <Panel title="Configuration" className="border-0" bodyClassName="p-0 pt-4">
            <RunConfigForm
              model={selectedModel}
              instruments={instruments}
              running={inFlight}
              onRun={(body) => void start(body)}
              onCancel={cancel}
              initialValues={initialValues}
            />
          </Panel>
        ) : modelsStatus === 'loading' ? (
          <EmptyState icon={Hourglass} title="Loading…" role="status" />
        ) : (
          <EmptyState
            testId="lab-nothing-to-configure"
            icon={SlidersHorizontal}
            title="Nothing to configure"
            detail="Register a signal strategy in the backend and its parameters and execution criteria appear here."
          />
        )}
      </CascadeItem>
    </div>
  );
}

import { BackendUnavailable, Loading } from '../components/StatusStates';
import { useWorkbench } from './WorkbenchContext';

/**
 * Every entry comes from the backend registry at request time — nothing about
 * model identity is hardcoded here, which is what makes registering a model
 * enough to make it appear (Constitution II).
 */
export function ModelCatalog() {
  const { models, modelsStatus, selected, setSelected } = useWorkbench();

  if (modelsStatus === 'loading') return <Loading />;
  if (modelsStatus === 'error') return <BackendUnavailable message="model catalog unavailable" />;

  return (
    <div className="h-full overflow-auto p-3" data-testid="model-catalog">
      <ul className="flex flex-col gap-2">
        {models.map((model) => {
          const isSelected = selected?.name === model.name && selected?.version === model.version;
          return (
            <li key={`${model.name}@${model.version}`}>
              <button
                type="button"
                onClick={() => setSelected(model)}
                aria-pressed={isSelected}
                className={`w-full rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  isSelected
                    ? 'border-primary bg-accent'
                    : 'border-border bg-card hover:bg-accent/50'
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">{model.name}</span>
                  <span className="text-xs text-muted-foreground">v{model.version}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{model.direction_semantics}</p>
                <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-muted-foreground">
                  <span className="rounded bg-muted px-1.5 py-0.5">
                    {model.parameters.length} parameter{model.parameters.length === 1 ? '' : 's'}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5">
                    lookback {model.lookback_days}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5">{model.scale_class}</span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

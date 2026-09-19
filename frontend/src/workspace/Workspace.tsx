import {
  DockviewReact,
  themeDark,
  themeLight,
  type DockviewReadyEvent,
  type IDockviewPanelProps,
} from 'dockview-react';
import { useEffect, useMemo, useState } from 'react';
import { PanelApiProvider } from '../components/usePanelSize';
import { useTheme } from '../theme/ThemeProvider';
import { buildDefaultLayout } from './defaultLayout';
import { PANELS, PANEL_IDS, type PanelId } from './panels';
import { restoreOrBuildDefault, useLayoutPersistence } from './useWorkspaceLayout';

export interface WorkspaceHandle {
  resetLayout: () => void;
}

/** Below this width, drag targets are too small to be usable, so we stack instead. */
const DOCKING_MIN_WIDTH = 768;

function useDockingViable(): boolean {
  const [viable, setViable] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return true;
    return window.matchMedia(`(min-width: ${DOCKING_MIN_WIDTH}px)`).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const query = window.matchMedia(`(min-width: ${DOCKING_MIN_WIDTH}px)`);
    const onChange = (event: MediaQueryListEvent) => setViable(event.matches);
    query.addEventListener?.('change', onChange);
    return () => query.removeEventListener?.('change', onChange);
  }, []);

  return viable;
}

/** Narrow screens get the panels stacked, with no docking chrome at all. */
function StackedPanels() {
  return (
    <div className="flex h-full flex-col gap-3 overflow-auto p-3">
      {PANEL_IDS.map((id) => {
        const Panel = PANELS[id].component;
        return (
          <section
            key={id}
            aria-label={PANELS[id].title}
            className="rounded-lg border border-border bg-card"
          >
            <h2 className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {PANELS[id].title}
            </h2>
            <div className="min-h-[240px]">
              <Panel />
            </div>
          </section>
        );
      })}
    </div>
  );
}

export function Workspace({
  onReady,
}: {
  onReady?: (handle: WorkspaceHandle) => void;
} = {}) {
  const { theme } = useTheme();
  const [api, setApi] = useState<DockviewReadyEvent['api'] | null>(null);
  const dockingViable = useDockingViable();

  // The one place that bridges dockview to panel content: each panel's api is
  // published through context, so content components (which must not import the
  // docking library) can still read their size via usePanelSize().
  const components = useMemo(
    () =>
      Object.fromEntries(
        PANEL_IDS.map((id) => {
          const Panel = PANELS[id].component;
          const Hosted = (props: IDockviewPanelProps) => (
            <PanelApiProvider value={props.api}>
              <Panel />
            </PanelApiProvider>
          );
          Hosted.displayName = `HostedPanel(${id})`;
          return [id, Hosted];
        }),
      ),
    [],
  );

  const handleReady = (event: DockviewReadyEvent) => {
    setApi(event.api);
    restoreOrBuildDefault(event.api);
    onReady?.({
      resetLayout: () => {
        event.api.clear();
        buildDefaultLayout(event.api);
      },
    });
  };

  useLayoutPersistence(api);

  // Which panels are currently open is derived from the live layout, so the
  // reopen affordance has to re-read it whenever the layout changes.
  const [layoutRevision, setLayoutRevision] = useState(0);
  useEffect(() => {
    if (!api) return;
    const subscription = api.onDidLayoutChange(() => setLayoutRevision((n) => n + 1));
    return () => subscription.dispose();
  }, [api]);

  const missingPanels = useMemo(
    () => (api ? PANEL_IDS.filter((id) => !api.getPanel(id)) : []),
    // layoutRevision is the trigger to re-derive from the live api.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [api, layoutRevision],
  );

  const reopen = (id: PanelId) => {
    if (!api) return;
    api.addPanel({ id, component: id, title: PANELS[id].title });
  };

  const openPanels = useMemo(
    () => (api ? PANEL_IDS.filter((id) => api.getPanel(id)) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [api, layoutRevision],
  );

  // Floating is offered as an explicit control, not only as a drag gesture, so
  // it stays reachable for keyboard and assistive-technology users (FR-014).
  const float = (id: PanelId) => {
    const panel = api?.getPanel(id);
    if (!api || !panel) return;
    api.addFloatingGroup(panel, { width: 640, height: 400 });
  };

  const chipClasses =
    'rounded border border-border bg-card px-2 py-0.5 font-medium text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

  if (!dockingViable) {
    return <StackedPanels />;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-muted px-3 py-1.5 text-xs">
        <span className="text-muted-foreground">Panels:</span>
        {openPanels.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => float(id)}
            aria-label={`Float ${PANELS[id].title} panel`}
            className={chipClasses}
          >
            Float {PANELS[id].title}
          </button>
        ))}
        {missingPanels.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => reopen(id)}
            aria-label={`Reopen ${PANELS[id].title} panel`}
            className={chipClasses}
          >
            Reopen {PANELS[id].title}
          </button>
        ))}
      </div>

      <DockviewReact
        className="min-h-0 flex-1"
        components={components}
        theme={theme === 'dark' ? themeDark : themeLight}
        onReady={handleReady}
      />
    </div>
  );
}

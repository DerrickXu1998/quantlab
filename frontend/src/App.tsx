import { DatasetProvider } from './api/DatasetProvider';
import { AuthGate } from './auth/AuthGate';
import { AuthProvider } from './auth/AuthProvider';
import { AppShell } from './chrome/AppShell';
import { RunsProvider } from './runs/RunsContext';

/**
 * The runs store is mounted inside the gate on purpose: it fetches the model
 * registry and the caller's runs the moment it exists, and firing those behind
 * a login screen would only produce a pair of 401s and an empty store to throw
 * away at sign-in.
 *
 * There is no boot animation. The app opens straight onto the workspace, and
 * the one entrance is the panel cascade in `CascadeItem` — 80ms apart, once.
 * A full-screen animated field before the terminal would be a second
 * high-impact moment competing with that one, a continuous animation beyond
 * the tick flash, and about two seconds standing between a trader and their
 * positions. It read as a product launch page, which this is not.
 */
export default function App() {
  return (
    <AuthProvider>
      <DatasetProvider>
        <AuthGate>
          <RunsProvider>
            <AppShell />
          </RunsProvider>
        </AuthGate>
      </DatasetProvider>
    </AuthProvider>
  );
}

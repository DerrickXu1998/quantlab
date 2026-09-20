import { useState } from 'react';
import { DatasetProvider } from './api/DatasetProvider';
import { AuthGate } from './auth/AuthGate';
import { AuthProvider } from './auth/AuthProvider';
import { AppShell } from './chrome/AppShell';
import { RunsProvider } from './runs/RunsContext';
import { SplashScreen } from './splash/SplashScreen';

/**
 * The runs store is mounted inside the gate on purpose: it fetches the model
 * registry and the caller's runs the moment it exists, and firing those behind
 * a login screen would only produce a pair of 401s and an empty store to throw
 * away at sign-in.
 */
function Workspace() {
  const [booting, setBooting] = useState(true);

  return (
    <RunsProvider>
      {/* Rendered over the shell rather than instead of it, so the page is
          already loaded and behind the field as it contracts away. It is a
          boot animation, not a per-destination one. */}
      {booting && <SplashScreen onComplete={() => setBooting(false)} />}
      <AppShell />
    </RunsProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <DatasetProvider>
        <AuthGate>
          <Workspace />
        </AuthGate>
      </DatasetProvider>
    </AuthProvider>
  );
}

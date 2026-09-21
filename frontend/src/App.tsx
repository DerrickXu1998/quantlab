import { useState } from 'react';
import { DatasetProvider } from './api/DatasetProvider';
import { AuthGate } from './auth/AuthGate';
import { AppShell } from './chrome/AppShell';
import { RunsProvider } from './runs/RunsContext';
import { SplashScreen } from './splash/SplashScreen';

export default function App() {
  const [booting, setBooting] = useState(true);

  return (
    <AuthGate>
      <DatasetProvider>
        <RunsProvider>
          {/* Rendered over the shell rather than instead of it, so the page is
              already loaded and behind the field as it contracts away. It is a
              boot animation, not a per-destination one. */}
          {booting && <SplashScreen onComplete={() => setBooting(false)} />}
          <AppShell />
        </RunsProvider>
      </DatasetProvider>
    </AuthGate>
  );
}

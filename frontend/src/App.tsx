import { useState } from 'react';
import { DatasetProvider } from './api/DatasetProvider';
import { QuantLabPage } from './quantlab/QuantLabPage';
import { SplashScreen } from './splash/SplashScreen';
import { SignalsSurface } from './surface/SignalsSurface';
import { useSurface } from './surface/useSurface';

export default function App() {
  const [booting, setBooting] = useState(true);
  const { surface, setSurface } = useSurface();

  return (
    <DatasetProvider>
      {/* Rendered over the workspace rather than instead of it, so the page
          is already loaded and behind the field as it contracts away. Shared
          by both surfaces: it is a boot animation, not a per-view one. */}
      {booting && <SplashScreen onComplete={() => setBooting(false)} />}

      {/* Conditional, never `hidden`: a display:none Dockview measures 0x0 and
          corrupts its layout. layoutStorage already restores it on return. */}
      {surface === 'lab' ? (
        <QuantLabPage onExit={() => setSurface('signals')} />
      ) : (
        <SignalsSurface onOpenLab={() => setSurface('lab')} />
      )}
    </DatasetProvider>
  );
}

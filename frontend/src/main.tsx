import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { ThemeProvider } from './theme/ThemeProvider';
// Dock chrome styles first, so the --dv-* overrides in styles.css win.
import 'dockview-react/dist/styles/dockview.css';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
);

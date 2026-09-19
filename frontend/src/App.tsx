import { SignalsPage } from './pages/SignalsPage';

export default function App() {
  return (
    <>
      <main>
        <SignalsPage />
      </main>
      <footer className="synthetic-notice">
        All instruments, prices, and signals shown here are synthetic and fictitious — demo data
        only, not real market data.
      </footer>
    </>
  );
}

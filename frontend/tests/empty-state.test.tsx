import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  BackendUnavailable,
  EmptyResults,
  Loading,
} from '../src/components/ui/empty-state';

describe('StatusStates', () => {
  it('renders the loading state as a polite status region', () => {
    render(<Loading />);

    const status = screen.getByRole('status');
    expect(status).toHaveTextContent(/loading signals/i);
    expect(status).toHaveClass('state-loading');
  });

  it('renders the empty-results state without any error styling or alert role', () => {
    render(<EmptyResults />);

    const empty = screen.getByTestId('empty-results');
    expect(empty).toHaveTextContent(/no signals match the current filters/i);
    expect(empty).toHaveClass('state-empty');
    expect(empty).not.toHaveClass('state-error');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('renders the backend-unavailable state as an alert with the error message', () => {
    render(<BackendUnavailable message="connect ECONNREFUSED" />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/backend unavailable/i);
    expect(alert).toHaveTextContent(/connect ECONNREFUSED/);
    expect(alert).toHaveClass('state-error');
  });

  it('renders a generic message when no error detail is provided', () => {
    render(<BackendUnavailable />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/backend unavailable/i);
    expect(alert).toHaveTextContent(/start the stack and reload this page/i);
  });

  it('keeps the stable identity hooks each state is addressed by after restyling', () => {
    render(
      <div>
        <Loading />
        <EmptyResults />
        <BackendUnavailable message="boom" />
      </div>,
    );

    // Restyle guard: styling may change freely, but these hooks are the contract
    // SignalsPage, the test suite, and assistive tech address these states by.
    expect(screen.getByRole('status')).toHaveClass('state', 'state-loading');
    expect(screen.getByTestId('empty-results')).toHaveClass('state', 'state-empty');
    expect(screen.getByTestId('backend-unavailable')).toHaveClass('state', 'state-error');
    expect(screen.getByTestId('backend-unavailable')).toHaveAttribute('role', 'alert');
  });

  it('keeps the backend error visually and semantically distinct from an empty list', () => {
    render(
      <div>
        <BackendUnavailable message="boom" />
        <EmptyResults />
      </div>,
    );

    const error = screen.getByTestId('backend-unavailable');
    const empty = screen.getByTestId('empty-results');

    expect(error).toHaveClass('state-error');
    expect(empty).not.toHaveClass('state-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(empty).not.toHaveAttribute('role', 'alert');
    expect(error).not.toHaveTextContent(/no signals match/i);
    expect(empty).not.toHaveTextContent(/backend unavailable/i);
  });
});

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../src/api/client';
import type { AuthContextValue } from '../../src/auth/AuthProvider';
import { LoginScreen, passwordStrength } from '../../src/auth/LoginScreen';

/**
 * The screen is driven through a stand-in context rather than a real provider:
 * what is under test here is the form's own behaviour — validation, the error
 * region, the pending state — and a real provider would only add a network
 * layer between the click and the assertion.
 */
const login = vi.fn<[{ email: string; password: string }], Promise<void>>();
const register = vi.fn<[{ email: string; password: string }], Promise<void>>();

vi.mock('../../src/auth/AuthProvider', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/auth/AuthProvider')>();
  return {
    ...actual,
    useAuth: (): AuthContextValue => ({
      user: null,
      token: null,
      status: 'anonymous',
      login,
      register,
      logout: async () => undefined,
    }),
  };
});

beforeEach(() => {
  login.mockReset();
  login.mockResolvedValue(undefined);
  register.mockReset();
  register.mockResolvedValue(undefined);
});

describe('password strength', () => {
  it('advises rather than gates, and says what would actually help', () => {
    expect(passwordStrength('').label).toBe('Empty');
    expect(passwordStrength('abc').label).toBe('Too short');
    expect(passwordStrength('abc').hint).toMatch(/you have 3/);
    expect(passwordStrength('password').label).toBe('Weak');
    expect(passwordStrength('Password1').label).toBe('Fair');
    expect(passwordStrength('correct-horse-battery').label).toBe('Good');
    expect(passwordStrength('Correct-Horse-9').label).toBe('Strong');
  });
});

describe('LoginScreen', () => {
  it('opens on sign in, with create account one tab away', () => {
    render(<LoginScreen />);

    expect(screen.getByRole('tab', { name: /sign in/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /create account/i })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('does not mark a half-typed email wrong while it is being typed', async () => {
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.type(screen.getByLabelText(/email/i), 'quant@');

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reports a malformed email once the field has been left', async () => {
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.type(screen.getByLabelText(/email/i), 'not-an-email');
    await person.tab();

    expect(await screen.findByRole('alert')).toHaveTextContent(/not an email address/i);
    expect(screen.getByLabelText(/email/i)).toHaveAttribute('aria-invalid', 'true');
  });

  it('refuses to submit an invalid form and says which field is wrong', async () => {
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.click(screen.getByRole('button', { name: /^sign in$/i }));

    expect(login).not.toHaveBeenCalled();
    const alerts = screen.getAllByRole('alert');
    expect(alerts.map((node) => node.textContent).join(' ')).toMatch(/email is required/i);
    expect(alerts.map((node) => node.textContent).join(' ')).toMatch(/password is required/i);
  });

  it('accepts a short password on the sign-in tab, because the server decides', async () => {
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.type(screen.getByLabelText(/email/i), 'quant@example.com');
    await person.type(screen.getByLabelText(/password/i), 'short');
    await person.click(screen.getByRole('button', { name: /^sign in$/i }));

    // Pre-judging a short password here would lock out a legitimate older
    // account whose password predates the current policy.
    await waitFor(() => expect(login).toHaveBeenCalledTimes(1));
  });

  it('requires the policy length before it will create an account', async () => {
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.click(screen.getByRole('tab', { name: /create account/i }));
    await person.type(screen.getByLabelText(/email/i), 'quant@example.com');
    await person.type(screen.getByLabelText(/password/i), 'short');
    await person.click(screen.getByRole('button', { name: /create account/i }));

    expect(register).not.toHaveBeenCalled();
    expect(screen.getAllByRole('alert').map((node) => node.textContent).join(' ')).toMatch(
      /at least 8 characters/i,
    );
  });

  it('shows the strength hint only on the register tab', async () => {
    const person = userEvent.setup();
    render(<LoginScreen />);

    expect(screen.queryByTestId('password-strength')).not.toBeInTheDocument();

    await person.click(screen.getByRole('tab', { name: /create account/i }));
    await person.type(screen.getByLabelText(/password/i), 'Correct-Horse-9');

    expect(screen.getByTestId('password-strength')).toHaveTextContent(/strong/i);
  });

  it('submits trimmed credentials and disables the button while it waits', async () => {
    let release = () => undefined as void;
    login.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          release = () => resolve();
        }),
    );
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.type(screen.getByLabelText(/email/i), '  quant@example.com  ');
    await person.type(screen.getByLabelText(/password/i), 'hunter22');
    await person.click(screen.getByRole('button', { name: /^sign in$/i }));

    const button = screen.getByRole('button', { name: /signing in/i });
    expect(button).toBeDisabled();
    expect(login).toHaveBeenCalledWith({ email: 'quant@example.com', password: 'hunter22' });

    release();
    await waitFor(() => expect(login).toHaveBeenCalledTimes(1));
  });

  it('turns a 401 into something a person can act on, in an alert region', async () => {
    login.mockRejectedValue(new ApiError(401, 'Unauthorized'));
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.type(screen.getByLabelText(/email/i), 'quant@example.com');
    await person.type(screen.getByLabelText(/password/i), 'wrong-password');
    await person.click(screen.getByRole('button', { name: /^sign in$/i }));

    const error = await screen.findByTestId('auth-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(error).toHaveTextContent(/email or password is incorrect/i);
    // Failing must not leave the button stuck in its pending state.
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeEnabled();
  });

  it('points an already-registered email at the sign-in tab instead of a status code', async () => {
    register.mockRejectedValue(new ApiError(409, 'conflict'));
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.click(screen.getByRole('tab', { name: /create account/i }));
    await person.type(screen.getByLabelText(/email/i), 'quant@example.com');
    await person.type(screen.getByLabelText(/password/i), 'hunter22-long');
    await person.click(screen.getByRole('button', { name: /create account/i }));

    expect(await screen.findByTestId('auth-error')).toHaveTextContent(/already registered/i);
  });

  it('keeps what was typed when the tabs are switched', async () => {
    const person = userEvent.setup();
    render(<LoginScreen />);

    await person.type(screen.getByLabelText(/email/i), 'quant@example.com');
    await person.click(screen.getByRole('tab', { name: /create account/i }));

    expect(screen.getByLabelText(/email/i)).toHaveValue('quant@example.com');
  });
});

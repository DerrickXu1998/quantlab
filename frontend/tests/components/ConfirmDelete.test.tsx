import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmDelete } from '../../src/components/ConfirmDelete';

describe('ConfirmDelete', () => {
  it('opens a confirmation popover and calls onConfirm', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();

    render(<ConfirmDelete label="Delete item" title="Delete" onConfirm={onConfirm} />);

    await user.click(screen.getByRole('button', { name: /delete item/i }));
    expect(screen.getByRole('dialog', { name: /confirm delete/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('closes the popover when Cancel is clicked', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();

    render(<ConfirmDelete label="Delete item" title="Delete" onConfirm={onConfirm} />);

    await user.click(screen.getByRole('button', { name: /delete item/i }));
    await user.click(screen.getByRole('button', { name: /^cancel$/i }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('closes the popover when Escape is pressed', async () => {
    const user = userEvent.setup();
    render(<ConfirmDelete label="Delete item" title="Delete" onConfirm={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: /delete item/i }));
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

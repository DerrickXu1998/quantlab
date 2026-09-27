import { Trash2 } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Button } from './ui/button';

/**
 * A delete button that expands into a small confirmation popover.
 *
 * The confirmation floats below the trigger instead of swapping inline, so
 * it does not widen a flex row or get clipped by an `overflow-hidden`
 * container. Clicking outside or pressing Escape cancels it.
 */
export function ConfirmDelete({
  label,
  title = 'Delete',
  onConfirm,
  disabled = false,
  variant = 'ghost',
  children,
}: {
  label: string;
  title?: string;
  onConfirm: () => void | Promise<void>;
  disabled?: boolean;
  variant?: 'ghost' | 'outline';
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const wrapperRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    function onMouseDown(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  return (
    <span ref={wrapperRef} className="relative inline-block">
      {!open ? (
        <Button
          type="button"
          size="sm"
          variant={variant}
          disabled={disabled}
          aria-label={label}
          title={title}
          onClick={() => setOpen(true)}
        >
          {children ?? <Trash2 size={16} strokeWidth={1.5} aria-hidden="true" />}
        </Button>
      ) : (
        <span
          className="absolute right-0 top-full z-10 mt-1 flex items-center gap-1 rounded-sm border border-border bg-card p-1"
          role="dialog"
          aria-label={`Confirm ${title.toLowerCase()}`}
        >
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            className="border-destructive/50 text-destructive hover:text-destructive"
            onClick={() => void handleConfirm()}
          >
            {busy ? 'Deleting…' : 'Confirm'}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => setOpen(false)}
          >
            Cancel
          </Button>
        </span>
      )}
    </span>
  );
}

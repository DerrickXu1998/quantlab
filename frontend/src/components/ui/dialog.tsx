import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useEffect, type ReactNode, type RefObject } from 'react';
import { cn } from '../../lib/utils';
import { Button } from './button';

/**
 * The one modal: a titled card over a dimmed page.
 *
 * Radix supplies what a hand-made dialog gets wrong: focus stays inside while
 * it is open and returns to the control that opened it, the page behind does
 * not scroll, and Escape or a click outside closes it.
 *
 * Mounted only while open, so the caller keeps a plain `open ? <Modal/> : null`.
 */
export function Modal({
  title,
  onClose,
  closeLabel,
  header,
  initialFocus,
  testId,
  className,
  children,
}: {
  title: string;
  onClose: () => void;
  /** Accessible name of the close button, e.g. "Close settings". */
  closeLabel: string;
  /** Extra header content between the title and the close button. */
  header?: ReactNode;
  /** Focused on open; the close button when omitted. */
  initialFocus?: RefObject<HTMLElement>;
  testId?: string;
  className?: string;
  children: ReactNode;
}) {
  // The modal is mounted only while open, so Radix never sees a trigger to
  // hand focus back to. Remember what had focus and return it once the focus
  // trap has gone, which is one tick after unmount.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      window.setTimeout(() => {
        if (opener?.isConnected) opener.focus();
      }, 0);
    };
  }, []);

  return (
    <DialogPrimitive.Root open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/80" />
        <div className="pointer-events-none fixed inset-0 z-50 flex items-start justify-center px-4 py-8">
          <DialogPrimitive.Content
            aria-describedby={undefined}
            data-testid={testId}
            onOpenAutoFocus={(event) => {
              if (!initialFocus?.current) return;
              event.preventDefault();
              initialFocus.current.focus();
            }}
            className={cn(
              'pointer-events-auto flex max-h-full w-full max-w-xl flex-col rounded-sm border border-border bg-card focus:outline-none',
              className,
            )}
          >
            <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
              <DialogPrimitive.Title className={cn('type-title', header ? undefined : 'flex-1')}>
                {title}
              </DialogPrimitive.Title>
              {header}
              <DialogPrimitive.Close asChild>
                <Button type="button" variant="ghost" size="sm" aria-label={closeLabel}>
                  <X size={16} strokeWidth={1.5} aria-hidden="true" />
                </Button>
              </DialogPrimitive.Close>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          </DialogPrimitive.Content>
        </div>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

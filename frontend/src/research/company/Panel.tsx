import { Hourglass, PlugZap, SearchX, ServerCrash, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from '../../components/ui/button';
import { Card, CardHeader, CardTitle } from '../../components/ui/card';
import { EmptyState } from '../../components/ui/empty-state';
import { cn } from '../../lib/utils';
import type { ReadStatus } from './useCompany';

/**
 * A panel that says what it is.
 *
 * The reported defect was not that the old panels were ugly, it was that
 * "Signals" and "Models" told a reader nothing about what they contained
 * (docs/RESEARCH.md §1a). `purpose` is therefore not decoration and not
 * optional: it is a required prop, so a panel added later cannot ship without
 * one sentence on its face explaining why it is on the screen.
 */
export function Panel({
  icon: Icon,
  title,
  purpose,
  aside,
  children,
  fill = false,
  className,
  testId,
}: {
  icon: LucideIcon;
  title: string;
  /** One line, in plain words, of what this panel is. Required by design. */
  purpose: string;
  aside?: ReactNode;
  children: ReactNode;
  /** Grow to fill the column and let the content scroll inside. */
  fill?: boolean;
  className?: string;
  testId?: string;
}) {
  return (
    <Card
      data-testid={testId}
      className={cn('flex min-h-0 flex-col', fill && 'flex-1', className)}
    >
      <CardHeader className="shrink-0">
        <div className="flex min-w-0 items-center gap-2">
          <Icon size={16} strokeWidth={1.5} className="shrink-0 text-muted-foreground" />
          <CardTitle className="truncate">{title}</CardTitle>
        </div>
        {aside ? <div className="flex shrink-0 items-center gap-2">{aside}</div> : null}
      </CardHeader>
      <p className="shrink-0 border-b border-border px-3 py-2 text-xs leading-relaxed text-muted-foreground">
        {purpose}
      </p>
      <div className={cn('flex min-h-0 flex-col', fill ? 'flex-1' : '')}>{children}</div>
    </Card>
  );
}

/**
 * The three states that are not "here is the answer".
 *
 * Each one is a sentence, never a bare spinner. `unsupported` is the state this
 * component exists for: while the route is being written, the honest answer is
 * "this deployment does not answer that yet", and rendering it as an empty
 * company would be a lie with the same shape as a finding.
 */
export function PanelState({
  status,
  message,
  /** What was being read, as a noun phrase: "the accounts as filed". */
  subject,
  /** The route that would answer it, named so the gap is diagnosable. */
  route,
  onRetry,
  testId,
}: {
  status: Exclude<ReadStatus, 'ready'>;
  message?: string | null;
  subject: string;
  route?: string;
  onRetry?: () => void;
  testId?: string;
}) {
  const retry = onRetry ? (
    <Button variant="outline" size="sm" onClick={onRetry}>
      Try again
    </Button>
  ) : null;

  if (status === 'loading') {
    return (
      <EmptyState
        icon={Hourglass}
        title={`Reading ${subject}…`}
        detail="One request, resolved as of the date above."
        role="status"
        testId={testId}
        className="my-4"
      />
    );
  }

  if (status === 'unsupported') {
    return (
      <EmptyState
        icon={PlugZap}
        title="Not served by this backend"
        detail={`${capitalise(subject)} would come from ${route ?? 'a route this deployment does not have'}.`}
        action={
          <Note>
            <p>
              This is a gap in the API, not a fact about the company. Nothing here means &ldquo;there
              is none&rdquo;.
            </p>
            {retry}
          </Note>
        }
        testId={testId}
        className="my-4"
      />
    );
  }

  return (
    <EmptyState
      icon={ServerCrash}
      tone="error"
      title="Could not read it"
      detail={`Reading ${subject} failed${message ? `: ${message}` : '.'}`}
      action={
        <Note>
          <p>The company may be fine; the request was not.</p>
          {retry}
        </Note>
      }
      testId={testId}
      className="my-4"
    />
  );
}

/**
 * The second sentence of a state, at a readable measure.
 *
 * `EmptyState` caps its own `detail` at a narrow column, which is right for the
 * one-line form and wrong for the explanation that has to follow "this route
 * does not exist yet". Placed in the action slot so the explanation gets the
 * panel's width and the primitive keeps its shape.
 */
function Note({ children }: { children: ReactNode }) {
  return (
    <div className="flex max-w-md flex-col items-center gap-2 text-xs leading-relaxed text-muted-foreground">
      {children}
    </div>
  );
}

/** Designed absence: nothing was there, and the panel says what that means. */
export function PanelEmpty({
  title,
  detail,
  icon = SearchX,
  testId,
}: {
  title: string;
  detail: string;
  icon?: LucideIcon;
  testId?: string;
}) {
  return (
    <EmptyState icon={icon} title={title} detail={detail} testId={testId} className="my-4" />
  );
}

function capitalise(text: string): string {
  return text.replace(/^./, (character) => character.toUpperCase());
}

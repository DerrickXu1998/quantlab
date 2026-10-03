import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../lib/utils';
import type { BarFrequency } from '../strategies/barFrequency';
import { paramUnit } from './params';
import { TERMS, type TermDefinition, type TermId } from './terms';
import { describeUnit, type UnitKind } from './units';

/**
 * The bar size the terms on screen are about. Units in bars are explained
 * against it ("14 bars ≈ 70 min on 5-minute bars"); without a provider they
 * read as daily.
 */
const FrequencyContext = createContext<BarFrequency>('1d');

export function GlossaryFrequency({
  frequency,
  children,
}: {
  frequency: BarFrequency;
  children: ReactNode;
}) {
  return <FrequencyContext.Provider value={frequency}>{children}</FrequencyContext.Provider>;
}

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground';
const WIDTH = 288;
const GAP = 6;

/**
 * A technical term with its explanation on hover, focus or tap.
 *
 * The label keeps its own styling (it sits inside mono caps labels and table
 * headers); a dotted underline is the only sign there is more to read. The
 * explanation is a tooltip, linked with aria-describedby, so a screen reader
 * hears it after the label without anyone hovering.
 */
export function Term({
  id,
  children,
  example,
  className,
}: {
  id: TermId;
  /** The label as shown; defaults to the glossary's own. */
  children?: ReactNode;
  /** The value on screen, when a bar count can be read back as time. */
  example?: number | null;
  className?: string;
}) {
  const definition: TermDefinition = TERMS[id];
  return (
    <Explained
      title={definition.label}
      body={definition.short}
      unit={definition.unit}
      example={example}
      className={className}
      testId={`term-${id}`}
    >
      {children ?? definition.label}
    </Explained>
  );
}

/**
 * A signal-rule parameter: the rule's own description (from the registry, so
 * `period` reads as RSI's in one rule and ADX's in another) with its unit.
 */
export function ParamTerm({
  rule,
  name,
  description,
  example,
  declaredUnit,
  children,
}: {
  rule: string;
  name: string;
  description?: string | null;
  example?: number | null;
  /** The unit line the backend declared for this parameter, when it did. */
  declaredUnit?: string | null;
  children?: ReactNode;
}) {
  return (
    <Explained
      title={name}
      body={description || 'A parameter of this rule.'}
      unit={paramUnit(rule, name)}
      unitText={declaredUnit}
      example={example}
      testId={`param-term-${name}`}
    >
      {children ?? name}
    </Explained>
  );
}

function Explained({
  title,
  body,
  unit,
  unitText,
  example,
  className,
  testId,
  children,
}: {
  title: string;
  body: string;
  unit?: UnitKind;
  unitText?: string | null;
  example?: number | null;
  className?: string;
  testId: string;
  children: ReactNode;
}) {
  const frequency = useContext(FrequencyContext);
  const tooltipId = useId();
  const anchor = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  const place = useCallback(() => {
    const box = anchor.current?.getBoundingClientRect();
    if (!box) return;
    const left = Math.min(Math.max(8, box.left), window.innerWidth - WIDTH - 8);
    // Below the term, unless that would leave the viewport.
    const below = box.bottom + GAP;
    const top = below + 160 > window.innerHeight ? Math.max(8, box.top - GAP - 160) : below;
    setPosition({ top, left });
  }, []);

  const show = () => {
    place();
    setOpen(true);
  };
  const hide = () => setOpen(false);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open, place]);

  const unitLine = unitText || (unit ? describeUnit(unit, frequency, example) : null);

  return (
    <>
      <span
        ref={anchor}
        tabIndex={0}
        data-testid={testId}
        aria-describedby={open ? tooltipId : undefined}
        // Read with the label even when closed, without a hidden copy of
        // the text in the page for every term on screen.
        aria-description={`${body}${unitLine ? ` Unit: ${unitLine}` : ''}`}
        className={cn(
          'cursor-help underline decoration-dotted decoration-muted-foreground/60 underline-offset-[3px]',
          'focus-visible:outline-none focus-visible:decoration-primary',
          className,
        )}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        // A tap on a touch screen: show it, and do not let a wrapping label
        // move focus into its input instead.
        onClick={(event) => {
          event.preventDefault();
          if (open) hide();
          else show();
        }}
      >
        {children}
      </span>
      {/* Rendered only while open: a page full of terms carries no hidden copies. */}
      {open && createPortal(
        <span
          id={tooltipId}
          role="tooltip"
          style={
            position ? { top: position.top, left: position.left, width: WIDTH } : { width: WIDTH }
          }
          className="pointer-events-none fixed z-50 block space-y-1.5 rounded-sm border border-border bg-card p-2.5 text-left normal-case tracking-normal"
        >
          <span className={cn(MICRO, 'block text-foreground')}>{title}</span>
          <span className="block text-xs leading-relaxed text-foreground">{body}</span>
          {unitLine ? (
            <span className="block border-t border-border pt-1.5 text-xs leading-relaxed text-muted-foreground">
              <span className={cn(MICRO, 'mr-1')}>Unit</span>
              {unitLine}
            </span>
          ) : null}
        </span>,
        document.body,
      )}
    </>
  );
}

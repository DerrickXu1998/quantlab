import { ArrowDown } from 'lucide-react';
import { useRef, useState, type MouseEvent, type ReactNode } from 'react';
import { Button } from '../../components/ui/button';
import { cn } from '../../lib/utils';
import {
  clamp,
  easeOut,
  pinnedProgress,
  useMediaQuery,
  useRevealed,
  useScrollFrame,
} from './motion';

/**
 * The signed-out front door, as one long scroll: a hero whose product shot
 * grows into place, a pinned tour where the product's real screens crossfade
 * as each chapter passes, what a backtest accounts for, and the way in.
 *
 * Every picture is a screenshot of the running product on real market history.
 * Every claim is one the product keeps, and the caveat at the foot is the
 * README's own.
 */

export type AuthMode = 'login' | 'register';

/**
 * One product picture, in two cuts: a wide one, and one taken at phone width
 * for small screens. Each is a whole panel of the running app, so nothing is
 * cropped by the page: the frame takes the picture's own shape.
 */
interface Picture {
  wide: { src: string; width: number; height: number };
  phone: { src: string; width: number; height: number };
  alt: string;
}

const picture = (
  name: string,
  wide: [number, number],
  phone: [number, number],
  alt: string,
): Picture => ({
  wide: { src: `/img/landing-${name}.webp`, width: wide[0], height: wide[1] },
  phone: { src: `/img/landing-${name}-phone.webp`, width: phone[0], height: phone[1] },
  alt,
});

const HERO = picture(
  'overview',
  [2880, 1800],
  [780, 1520],
  'QuantLab showing a finished backtest: its book value, its equity curve against buy-and-hold, and its open positions',
);

interface Chapter {
  id: string;
  eyebrow: string;
  headline: string;
  /** `lead` reads in the foreground colour, `rest` in the muted one. */
  lead: string;
  rest: string;
  picture: Picture;
}

const CHAPTERS: Chapter[] = [
  {
    id: 'build',
    eyebrow: 'Build',
    headline: 'No code. Just rules.',
    lead: 'Pick signal rules and give each a role: entry, exit or filter.',
    rest: 'Choose how they combine, and QuantLab reads the whole strategy back to you in one plain sentence.',
    picture: picture(
      'build',
      [2180, 1296],
      [704, 788],
      'A strategy made of two rules: a momentum rule that opens a position and one that closes it, each with its settings',
    ),
  },
  {
    id: 'backtest',
    eyebrow: 'Backtest',
    headline: 'Every trade, replayed.',
    lead: 'Run it over real market history, then watch it trade bar by bar.',
    rest: 'Equity, cash and open positions move as the strategy would have moved them.',
    picture: picture(
      'replay',
      [2240, 1484],
      [756, 1000],
      'A replayed backtest: equity, cash, open positions and realised profit at the final bar, above the equity curve for the year',
    ),
  },
  {
    id: 'research',
    eyebrow: 'Research',
    headline: 'Any company. Any date.',
    lead: 'See prices, signals and filed fundamentals exactly as they stood on the day you pick.',
    rest: 'Nothing from the future leaks into your research.',
    picture: picture(
      'research',
      [2876, 1546],
      [1264, 1518],
      'A company price chart over eleven years, beside a model that can be run over its history',
    ),
  },
  {
    id: 'market',
    eyebrow: 'Market',
    headline: 'Charts that keep up.',
    lead: 'Chart up to four tickers side by side, with the studies you already use.',
    rest: 'Daily history is built in, and live intraday prices come from your own broker login.',
    picture: picture(
      'market',
      [2284, 1422],
      [772, 872],
      'A one-year daily candlestick chart with volume, and the latest bar read out above it',
    ),
  },
];

const FACTS: { title: string; detail: string }[] = [
  {
    title: 'Commissions and slippage',
    detail: 'Set a rate for each, and every fill pays it.',
  },
  {
    title: 'Realistic fill timing',
    detail: 'Fill at the next bar’s open: the first price you could really have traded.',
  },
  {
    title: 'Volume limits',
    detail: 'Cap each order at a share of the bar’s volume, as a real one would be.',
  },
  {
    title: 'A benchmark that matters',
    detail: 'Every result is scored against buying and holding the same stocks.',
  },
];

const PHONE = '(max-width: 639px)';

/**
 * A product picture, whole. The image keeps its own proportions and the
 * hairline frame is drawn on the image itself, so the frame is exactly the
 * picture and never trims it. `contain` fits it inside a box of fixed size
 * (the pinned stages); otherwise it fills the width it is given.
 */
function Shot({
  picture: { wide, phone, alt },
  eager,
  contain,
  className,
}: {
  picture: Picture;
  eager?: boolean;
  contain?: boolean;
  className?: string;
}) {
  return (
    <picture className={contain ? 'contents' : 'block'}>
      <source media={PHONE} srcSet={phone.src} width={phone.width} height={phone.height} />
      <img
        src={wide.src}
        alt={alt}
        width={wide.width}
        height={wide.height}
        loading={eager ? 'eager' : 'lazy'}
        decoding="async"
        className={cn(
          contain
            ? 'h-auto max-h-full w-auto max-w-full'
            : 'block h-auto w-full rounded-sm border border-border bg-card',
          className,
        )}
      />
    </picture>
  );
}

/** Fades and lifts its children into place the first time they are seen. */
function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const [ref, shown] = useRevealed<HTMLDivElement>();
  return (
    <div
      ref={ref}
      className={cn(
        'transition-[opacity,transform] duration-700 ease-out',
        shown ? 'translate-y-0 opacity-100' : 'translate-y-6 opacity-0',
        className,
      )}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

/**
 * Pinned to the top for the whole scroll, so the way in is always one click
 * away. Links, not buttons: they move the visitor to the form further down.
 */
export function LandingNav({ onGo }: { onGo: (mode: AuthMode) => void }) {
  const bar = useRef<HTMLElement>(null);
  const [solid, setSolid] = useState(false);
  useScrollFrame(() => {
    const next = window.scrollY > 24;
    setSolid((current) => (current === next ? current : next));
  });

  const go = (mode: AuthMode) => (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    onGo(mode);
  };

  return (
    <header
      ref={bar}
      className={cn(
        'fixed inset-x-0 top-0 z-40 border-b transition-colors duration-300',
        solid ? 'border-border bg-background' : 'border-transparent bg-transparent',
      )}
    >
      <nav
        aria-label="QuantLab"
        className="mx-auto flex h-14 w-full max-w-[84rem] items-center gap-2 px-4 lg:px-8"
      >
        <p className="flex-1 font-display text-lg tracking-[-0.02em]">QuantLab</p>
        <Button asChild variant="ghost" size="sm">
          <a href="#sign-in" onClick={go('login')}>
            Sign in
          </a>
        </Button>
        <Button asChild size="sm">
          <a href="#sign-in" onClick={go('register')}>
            Create account
          </a>
        </Button>
      </nav>
    </header>
  );
}

function HeroCopy({ onGo }: { onGo: (mode: AuthMode) => void }) {
  return (
    <>
      <p className="type-label text-primary">Systematic stock research</p>
      <h1
        id="landing-headline"
        className="mx-auto mt-5 max-w-4xl text-balance font-display text-5xl leading-[1.02] tracking-[-0.03em] sm:text-6xl lg:text-7xl"
      >
        Does your strategy beat buy-and-hold?
      </h1>
      <p className="mx-auto mt-6 max-w-2xl text-pretty text-lg leading-relaxed text-muted-foreground">
        Build a trading strategy, test it on real market history, and see what it would have earned.
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Button asChild>
          <a
            href="#sign-in"
            onClick={(event) => {
              event.preventDefault();
              onGo('register');
            }}
          >
            Create account
          </a>
        </Button>
        <Button asChild variant="ghost">
          <a
            href="#tour"
            onClick={(event) => {
              event.preventDefault();
              document.getElementById('tour')?.scrollIntoView?.({ behavior: 'smooth' });
            }}
          >
            See how it works
            <ArrowDown size={16} strokeWidth={1.5} aria-hidden="true" />
          </a>
        </Button>
      </div>
    </>
  );
}

/**
 * The opening on a wide screen: the question, with the product waiting below
 * the fold line. Scrolling pins the screen, lets the words go and brings the
 * product up to fill it. The picture is sized from the viewport's height as
 * well as its width, so at rest it is whole: nothing runs off the bottom.
 */
function PinnedHero({ onGo }: { onGo: (mode: AuthMode) => void }) {
  const track = useRef<HTMLDivElement>(null);
  const copy = useRef<HTMLDivElement>(null);
  const shot = useRef<HTMLDivElement>(null);

  useScrollFrame(() => {
    if (!track.current) return;
    // The move finishes at 80% of the travel, so the product holds still for
    // a moment before the page moves on.
    const progress = clamp(pinnedProgress(track.current) / 0.8);
    const t = easeOut(progress);
    if (shot.current) {
      const start = window.innerHeight * 0.5;
      shot.current.style.transform = `translate3d(0, ${(1 - t) * start}px, 0) scale(${0.8 + 0.2 * t})`;
    }
    if (copy.current) {
      const gone = clamp(progress / 0.45);
      copy.current.style.opacity = String(1 - gone);
      copy.current.style.transform = `translate3d(0, ${gone * -48}px, 0)`;
      copy.current.style.pointerEvents = gone > 0.5 ? 'none' : 'auto';
    }
  });

  return (
    <div ref={track} style={{ height: '200vh' }}>
      <div className="sticky top-0 h-screen overflow-hidden">
        <div ref={copy} className="relative z-10 px-8 pt-28 text-center will-change-transform">
          <HeroCopy onGo={onGo} />
        </div>
        <div className="absolute inset-x-0 bottom-0 top-14 flex items-center justify-center px-8 py-6">
          <div
            ref={shot}
            className="flex h-full w-full max-w-[84rem] origin-top items-center justify-center will-change-transform"
            style={{ transform: 'translate3d(0, 50vh, 0) scale(0.8)' }}
          >
            <Shot picture={HERO} eager contain />
          </div>
        </div>
      </div>
    </div>
  );
}

/** The opening for a phone or for reduced motion: the words, then the product. */
function StackedHero({ onGo }: { onGo: (mode: AuthMode) => void }) {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-8 pt-28 text-center lg:px-8">
      <HeroCopy onGo={onGo} />
      <Reveal className="mx-auto mt-12 max-w-sm sm:max-w-none">
        <Shot picture={HERO} eager />
      </Reveal>
    </div>
  );
}

const PINNED =
  '(min-width: 1024px) and (min-height: 640px) and (prefers-reduced-motion: no-preference)';

function Hero({ onGo }: { onGo: (mode: AuthMode) => void }) {
  const pinned = useMediaQuery(PINNED);
  return (
    <section aria-labelledby="landing-headline" data-testid="landing-pitch">
      {pinned ? <PinnedHero onGo={onGo} /> : <StackedHero onGo={onGo} />}
    </section>
  );
}

function ChapterCopy({ chapter }: { chapter: Chapter }) {
  return (
    <>
      <p className="type-label text-primary">{chapter.eyebrow}</p>
      <h2 className="mt-4 text-balance font-display text-4xl leading-[1.05] tracking-[-0.02em] sm:text-5xl">
        {chapter.headline}
      </h2>
      <p className="mt-5 text-pretty text-lg leading-relaxed text-muted-foreground">
        <span className="text-foreground">{chapter.lead}</span> {chapter.rest}
      </p>
    </>
  );
}

/**
 * The tour on a wide screen: the section is several screens tall and its
 * content is pinned, so scrolling does not move the page, it moves the story.
 * Each chapter's words rise and fade as the next screenshot dissolves in.
 */
function PinnedTour() {
  const track = useRef<HTMLDivElement>(null);
  const copies = useRef<(HTMLDivElement | null)[]>([]);
  const shots = useRef<(HTMLDivElement | null)[]>([]);
  const meter = useRef<HTMLSpanElement>(null);

  useScrollFrame(() => {
    if (!track.current) return;
    const progress = pinnedProgress(track.current);
    // A continuous position along the chapters: 1.5 is halfway from the
    // second to the third.
    const position = progress * (CHAPTERS.length - 1);

    CHAPTERS.forEach((_, index) => {
      const distance = position - index;

      // Words hand over at the halfway point: the outgoing chapter rises and
      // fades over the step's middle fifth, the incoming one follows straight
      // after, so two chapters are never legible at once and never both gone
      // for more than a beat.
      const copy = copies.current[index];
      if (copy) {
        const out = clamp((distance - 0.32) / 0.16); // leaving, upwards
        const into = clamp((-distance - 0.32) / 0.16); // not here yet
        const presence = easeOut(1 - Math.max(out, into));
        copy.style.opacity = String(presence);
        copy.style.transform = `translate3d(0, ${(into - out) * 40}px, 0)`;
        copy.style.pointerEvents = presence > 0.5 ? 'auto' : 'none';
      }

      // Pictures dissolve: each fades in on top of the one before, which stays
      // fully opaque underneath until it is covered. The frame is never empty
      // and never dims.
      const shot = shots.current[index];
      if (shot) {
        const arrival = index === 0 ? 1 : easeOut(clamp((distance + 0.6) / 0.2));
        const covered = index === CHAPTERS.length - 1 ? 0 : clamp((distance - 0.4) / 0.2);
        shot.style.opacity = String(covered >= 1 ? 0 : arrival);
        shot.style.transform = `scale(${0.985 + 0.015 * arrival})`;
      }
    });

    if (meter.current) meter.current.style.transform = `scaleY(${progress})`;
  });

  return (
    <div ref={track} style={{ height: `${CHAPTERS.length * 100}vh` }}>
      <div className="sticky top-0 flex h-screen items-center overflow-hidden">
        <div className="mx-auto grid w-full max-w-[84rem] grid-cols-[minmax(0,23rem)_minmax(0,1fr)] items-center gap-12 px-8 pt-14">
          <div className="relative flex h-96 gap-6">
            <span aria-hidden="true" className="relative w-px shrink-0 bg-border">
              <span
                ref={meter}
                className="absolute inset-0 origin-top bg-primary will-change-transform"
                style={{ transform: 'scaleY(0)' }}
              />
            </span>
            <div className="relative flex-1">
              {CHAPTERS.map((chapter, index) => (
                <div
                  key={chapter.id}
                  ref={(node) => {
                    copies.current[index] = node;
                  }}
                  className="absolute inset-0 flex flex-col justify-center will-change-transform"
                  style={{ opacity: index === 0 ? 1 : 0 }}
                >
                  <ChapterCopy chapter={chapter} />
                </div>
              ))}
            </div>
          </div>

          {/* The stage: one window, the same size for every chapter. Each
              picture sits whole and centred in it on a solid ground, so the
              next window covers the last one completely as it fades in. The
              window is a screen, so it stays dark in either theme. */}
          <div className="relative h-[min(34rem,calc(100vh-12rem))]">
            {CHAPTERS.map((chapter, index) => (
              <div
                key={chapter.id}
                ref={(node) => {
                  shots.current[index] = node;
                }}
                className="dark absolute inset-0 flex items-center justify-center rounded-sm border border-border bg-card p-5 will-change-transform"
                style={{ opacity: index === 0 ? 1 : 0, zIndex: index }}
              >
                <Shot picture={chapter.picture} eager={index === 0} contain />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The same tour for a phone or for reduced motion: one chapter after another. */
function StackedTour() {
  return (
    <div className="mx-auto w-full max-w-3xl space-y-24 px-4 py-20 lg:px-8">
      {CHAPTERS.map((chapter) => (
        <Reveal key={chapter.id}>
          <ChapterCopy chapter={chapter} />
          <div className="mx-auto mt-8 max-w-sm sm:max-w-none">
            <Shot picture={chapter.picture} />
          </div>
        </Reveal>
      ))}
    </div>
  );
}

function Tour() {
  const pinned = useMediaQuery(PINNED);
  return (
    <section id="tour" aria-label="What QuantLab does" className="scroll-mt-14">
      {pinned ? <PinnedTour /> : <StackedTour />}
    </section>
  );
}

function Facts() {
  return (
    <section
      aria-labelledby="landing-facts"
      className="mx-auto w-full max-w-[84rem] px-4 py-24 lg:px-8 lg:py-36"
    >
      <Reveal className="mx-auto max-w-3xl text-center">
        <p className="type-label text-primary">Honest results</p>
        <h2
          id="landing-facts"
          className="mt-4 text-balance font-display text-4xl leading-[1.05] tracking-[-0.02em] sm:text-6xl"
        >
          Costs included.
        </h2>
        <p className="mt-5 text-pretty text-lg leading-relaxed text-muted-foreground">
          A backtest that trades for free at perfect prices tells you nothing.{' '}
          <span className="text-foreground">
            QuantLab lets you charge what a real one would pay.
          </span>
        </p>
      </Reveal>

      <ul className="mt-14 grid gap-px border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {FACTS.map((fact, index) => (
          <li key={fact.title} className="bg-background">
            <Reveal delay={index * 90} className="h-full p-6">
              <p className="type-data text-primary">{String(index + 1).padStart(2, '0')}</p>
              <p className="mt-4 type-title">{fact.title}</p>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{fact.detail}</p>
            </Reveal>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Everything above the sign-in form. */
export function LandingStory({ onGo }: { onGo: (mode: AuthMode) => void }) {
  return (
    <>
      <Hero onGo={onGo} />
      <Tour />
      <Facts />
    </>
  );
}

/** The close: the form's heading, the form itself, and the fine print. */
export function LandingClose({ children }: { children: ReactNode }) {
  return (
    <section
      id="sign-in"
      aria-labelledby="landing-close"
      className="scroll-mt-14 border-t border-border"
    >
      <div className="mx-auto grid w-full max-w-[84rem] items-center gap-12 px-4 py-24 lg:grid-cols-[minmax(0,1fr)_24rem] lg:gap-16 lg:px-8 lg:py-32">
        <Reveal>
          <h2
            id="landing-close"
            className="text-balance font-display text-4xl leading-[1.05] tracking-[-0.02em] sm:text-6xl"
          >
            Test your first strategy today.
          </h2>
          <p className="mt-5 max-w-xl text-pretty text-lg leading-relaxed text-muted-foreground">
            Build it, run it, and see how it would have done against simply holding the stocks.
          </p>
        </Reveal>
        {children}
      </div>
      <p className="mx-auto w-full max-w-[84rem] px-4 pb-10 text-xs leading-relaxed text-muted-foreground lg:px-8">
        Backtests use today&apos;s S&amp;P 500 members, so results are not corrected for
        survivorship bias. Nothing here is investment advice.
      </p>
    </section>
  );
}

import { ArrowDown } from 'lucide-react';
import { useRef, useState, type MouseEvent, type ReactNode } from 'react';
import { Button } from '../../components/ui/button';
import { cn } from '../../lib/utils';
import {
  clamp,
  easeOut,
  pinnedProgress,
  useMediaQuery,
  useReducedMotion,
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

const SHOT = { width: 2400, height: 1500 };

interface Chapter {
  id: string;
  eyebrow: string;
  headline: string;
  /** `lead` reads in the foreground colour, `rest` in the muted one. */
  lead: string;
  rest: string;
  image: string;
  alt: string;
}

const CHAPTERS: Chapter[] = [
  {
    id: 'build',
    eyebrow: 'Build',
    headline: 'No code. Just rules.',
    lead: 'Pick signal rules and give each a role: entry, exit or filter.',
    rest: 'Choose how they combine, and QuantLab reads the whole strategy back to you in one plain sentence.',
    image: '/img/landing-strategies.webp',
    alt: 'The Strategies screen: a momentum strategy built from an entry rule and an exit rule, described in one sentence above them',
  },
  {
    id: 'backtest',
    eyebrow: 'Backtest',
    headline: 'Every trade, replayed.',
    lead: 'Run it over real market history, then watch it trade bar by bar.',
    rest: 'Equity, cash and open positions move as the strategy would have moved them.',
    image: '/img/landing-replay.webp',
    alt: 'The Replay screen: a finished backtest with its equity curve, ready to play back one bar at a time',
  },
  {
    id: 'research',
    eyebrow: 'Research',
    headline: 'Any company. Any date.',
    lead: 'See prices, signals and filed fundamentals exactly as they stood on the day you pick.',
    rest: 'Nothing from the future leaks into your research.',
    image: '/img/landing-research.webp',
    alt: 'The Research screen: a company price chart cut at a chosen date, beside a model that marks its signals on the chart',
  },
  {
    id: 'market',
    eyebrow: 'Market',
    headline: 'Charts that keep up.',
    lead: 'Chart up to four tickers side by side, with the studies you already use.',
    rest: 'Daily history is built in, and live intraday prices come from your own broker login.',
    image: '/img/landing-market.webp',
    alt: 'The Market screen: a daily candlestick chart with moving averages and a list of instruments to chart',
  },
];

const FACTS: { title: string; detail: string }[] = [
  {
    title: 'Commissions and slippage',
    detail: 'Every fill pays both, at rates you set.',
  },
  {
    title: 'Realistic fill timing',
    detail:
      'A signal on today’s close fills at the next bar’s open, the first price you could have traded.',
  },
  {
    title: 'Volume limits',
    detail: 'An order cannot take more of a bar’s volume than a real one could.',
  },
  {
    title: 'A benchmark that matters',
    detail: 'Every result is scored against buying and holding the same stocks.',
  },
];

/**
 * A product screenshot in the page's one frame: a hairline, no shadow.
 *
 * A full desktop screen shrunk to a phone's width is unreadable, so on a phone
 * the frame shows the top-left of the screen at a size that can be read.
 */
function Shot({
  src,
  alt,
  eager,
  className,
}: {
  src: string;
  alt: string;
  eager?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'aspect-[4/3] overflow-hidden rounded-sm border border-border bg-card sm:aspect-auto',
        className,
      )}
    >
      <img
        src={src}
        alt={alt}
        width={SHOT.width}
        height={SHOT.height}
        loading={eager ? 'eager' : 'lazy'}
        decoding="async"
        className="block w-[190%] max-w-none sm:w-full"
      />
    </div>
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
        className="mx-auto flex h-14 w-full max-w-7xl items-center gap-2 px-4 lg:px-8"
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

/**
 * The opening: the question, then the product. The screenshot starts small and
 * low and grows to full width over the first screen of scrolling.
 */
function Hero({ onGo }: { onGo: (mode: AuthMode) => void }) {
  const reduced = useReducedMotion();
  const shot = useRef<HTMLDivElement>(null);
  const copy = useRef<HTMLDivElement>(null);

  useScrollFrame(() => {
    const t = easeOut(clamp(window.scrollY / (window.innerHeight * 0.7)));
    if (shot.current) {
      shot.current.style.transform = `translate3d(0, ${(1 - t) * 48}px, 0) scale(${0.86 + 0.14 * t})`;
    }
    if (copy.current) {
      // The words give way as the product arrives.
      const fade = clamp(window.scrollY / (window.innerHeight * 0.55));
      copy.current.style.opacity = String(1 - fade * 0.85);
      copy.current.style.transform = `translate3d(0, ${fade * -24}px, 0)`;
    }
  }, !reduced);

  return (
    <section
      aria-labelledby="landing-headline"
      data-testid="landing-pitch"
      className="mx-auto w-full max-w-7xl px-4 pb-16 pt-28 text-center lg:px-8 lg:pt-36"
    >
      <div ref={copy} className="will-change-transform">
        <p className="type-label text-primary">Systematic stock research</p>
        <h1
          id="landing-headline"
          className="mx-auto mt-5 max-w-4xl text-balance font-display text-5xl leading-[1.02] tracking-[-0.03em] sm:text-6xl lg:text-7xl"
        >
          Does your strategy beat buy-and-hold?
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-pretty text-lg leading-relaxed text-muted-foreground">
          Build a trading strategy, test it on real market history, and see what it would have
          earned after costs.
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
            <a href="#tour">
              See how it works
              <ArrowDown size={16} strokeWidth={1.5} aria-hidden="true" />
            </a>
          </Button>
        </div>
      </div>

      <div
        ref={shot}
        className="mt-14 origin-top will-change-transform"
        style={reduced ? undefined : { transform: 'translate3d(0, 48px, 0) scale(0.86)' }}
      >
        <Shot
          eager
          src="/img/landing-overview.webp"
          alt="The Overview screen: a backtest's book value and equity curve against buy-and-hold, with its open positions"
        />
      </div>
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
      const away = Math.abs(distance);

      // Words hand off cleanly: each is gone before the halfway point, so two
      // chapters are never legible on top of each other.
      const copy = copies.current[index];
      if (copy) {
        const presence = clamp(1 - (away - 0.12) / 0.3);
        copy.style.opacity = String(presence);
        copy.style.transform = `translate3d(0, ${distance * -72}px, 0)`;
        copy.style.pointerEvents = presence > 0.5 ? 'auto' : 'none';
      }

      // Pictures dissolve quickly around the halfway point: each fades and
      // rises in on top of the one before, which stays opaque underneath, so
      // the frame never dims and two screens are only briefly mixed.
      const shot = shots.current[index];
      if (shot) {
        const arrival = index === 0 ? 1 : easeOut(clamp((distance + 0.64) / 0.28));
        shot.style.opacity = String(arrival);
        shot.style.transform = `translate3d(0, ${(1 - arrival) * 28}px, 0)`;
      }
    });

    if (meter.current) meter.current.style.transform = `scaleY(${progress})`;
  });

  return (
    <div ref={track} style={{ height: `${CHAPTERS.length * 100}vh` }}>
      <div className="sticky top-0 flex h-screen items-center overflow-hidden">
        <div className="mx-auto grid w-full max-w-7xl grid-cols-[minmax(0,20rem)_minmax(0,1fr)] items-center gap-12 px-8 pt-14">
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

          <div className="relative" style={{ aspectRatio: `${SHOT.width} / ${SHOT.height}` }}>
            {CHAPTERS.map((chapter, index) => (
              <div
                key={chapter.id}
                ref={(node) => {
                  shots.current[index] = node;
                }}
                className="absolute inset-0 will-change-transform"
                style={{ opacity: index === 0 ? 1 : 0 }}
              >
                <Shot src={chapter.image} alt={chapter.alt} eager={index === 0} />
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
          <Shot src={chapter.image} alt={chapter.alt} className="mt-8" />
        </Reveal>
      ))}
    </div>
  );
}

function Tour() {
  const pinned = useMediaQuery('(min-width: 1024px) and (prefers-reduced-motion: no-preference)');
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
      className="mx-auto w-full max-w-7xl px-4 py-24 lg:px-8 lg:py-36"
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
          <span className="text-foreground">Every QuantLab run pays what a real one would.</span>
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
      <div className="mx-auto grid w-full max-w-7xl items-center gap-12 px-4 py-24 lg:grid-cols-[minmax(0,1fr)_24rem] lg:gap-16 lg:px-8 lg:py-32">
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
      <p className="mx-auto w-full max-w-7xl px-4 pb-10 text-xs leading-relaxed text-muted-foreground lg:px-8">
        Backtests use today&apos;s S&amp;P 500 members, so results are not corrected for
        survivorship bias. Nothing here is investment advice.
      </p>
    </section>
  );
}

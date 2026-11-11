import { Clock, FlaskConical, Search, type LucideIcon } from 'lucide-react';

/**
 * What QuantLab is, for someone who has not signed in yet.
 *
 * Every claim here is one the product already keeps, and the caveat under the
 * list is the README's own: backtests run over today's S&P 500 members, so
 * they are not corrected for survivorship bias. Saying so on the front door is
 * cheaper than a visitor finding it out later.
 */
const POINTS: { icon: LucideIcon; title: string; detail: string }[] = [
  {
    icon: FlaskConical,
    title: 'Compose strategies from signal rules',
    detail:
      'Give each rule a role (entry, exit or filter), choose how they combine, and read the result back as one plain sentence. No code.',
  },
  {
    icon: Clock,
    title: 'Backtest in the background, on real history',
    detail:
      'Runs model commissions, slippage, fill timing and volume limits, and report against buy-and-hold of the same names.',
  },
  {
    icon: Search,
    title: 'Research any company as of any date',
    detail:
      'Prices, signals and fundamentals as they had been filed on the day you pick, so nothing leaks in from the future.',
  },
];

export function LandingPitch() {
  return (
    <section aria-labelledby="landing-headline" data-testid="landing-pitch" className="max-w-xl">
      <p className="font-display text-xl tracking-[-0.02em]">QuantLab</p>

      <h1
        id="landing-headline"
        className="mt-8 text-balance font-display text-4xl leading-[1.05] tracking-[-0.02em] sm:text-5xl"
      >
        Build a strategy. Backtest it. See if it beats buy-and-hold.
      </h1>
      <p className="mt-4 text-base leading-relaxed text-muted-foreground">
        A research workbench for systematic equity strategies, on real market history.
      </p>

      <ul className="mt-8 space-y-5">
        {POINTS.map((point) => (
          <li key={point.title} className="flex gap-3">
            <point.icon
              size={20}
              strokeWidth={1.5}
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-primary"
            />
            <div>
              <p className="text-sm font-medium">{point.title}</p>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{point.detail}</p>
            </div>
          </li>
        ))}
      </ul>

      <img
        src="/img/product-market.png"
        alt="QuantLab's Market screen: two daily candlestick charts side by side with moving averages"
        width={1440}
        height={900}
        loading="lazy"
        className="mt-10 hidden w-full rounded-sm border border-border lg:block"
      />

      <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
        Backtests cover a fixed universe of current S&amp;P 500 members and are not corrected for
        survivorship bias. Nothing here is investment advice.
      </p>
    </section>
  );
}

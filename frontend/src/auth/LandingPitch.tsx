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
    title: 'Build a strategy without code',
    detail:
      'Pick signal rules, give each a role (entry, exit or filter) and choose how they combine. QuantLab reads the strategy back to you in one plain sentence.',
  },
  {
    icon: Clock,
    title: 'Backtest it with realistic costs',
    detail:
      'Every run pays commissions and slippage, fills at realistic times and respects volume limits. Results are scored against buy-and-hold of the same stocks.',
  },
  {
    icon: Search,
    title: 'Research any company as of any date',
    detail:
      'See prices, signals and filed fundamentals exactly as they stood on the day you pick, so nothing from the future leaks into your research.',
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
        Find out if your trading strategy beats buy-and-hold.
      </h1>
      <p className="mt-4 text-base leading-relaxed text-muted-foreground">
        QuantLab is a research workbench for systematic stock strategies. Build one, test it on real
        market history, and see what it would have earned after costs.
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
        Backtests use today&apos;s S&amp;P 500 members, so results are not corrected for
        survivorship bias. Nothing here is investment advice.
      </p>
    </section>
  );
}

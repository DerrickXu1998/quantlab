# Free data sources for a NYSE + LSE universe

Verified September 2026. Free tiers change often and usually for the worse — re-check
before you depend on any of these. Where something could not be confirmed against an
official page it is marked **unverified** rather than guessed at.

## The short version

**There is no free, licensed, API-based source of LSE daily OHLCV at 5,000-name scale.**
That is the binding constraint on this whole project and it is worth deciding about now.
Your two practical options for the UK half are Stooq and Yahoo (via `yfinance`) — both
unofficial, neither licensed for redistribution. US data, by contrast, is genuinely well
served: SEC EDGAR alone is public domain and commercially usable.

If the project ever becomes anything other than personal research, budget roughly
$30–80/month for the UK half and treat the free sources as redundancy.

## Build order

| # | Source | What it gives you | Why this rank |
|---|--------|-------------------|---------------|
| 1 | **Stooq** | Daily OHLCV, US + UK, 30+ years | Only free source covering **both** markets. No key, no registration, no symbol cap. |
| 2 | **Yahoo** (`yfinance`) | OHLCV, **corporate actions**, metadata | Best LSE coverage, and the only free source of UK dividends/splits. Breaks periodically — use as the fallback, not the primary. |
| 3 | **SEC EDGAR** | US fundamentals, insider Form 4 | Free, official, public domain, no key, deep history. Solves US fundamentals completely. |
| 4 | **Companies House** | UK fundamentals (iXBRL accounts) | The only free path to UK financials. Real work to parse, but without it your LSE half has prices and nothing else. |
| + | **OpenFIGI** | Ticker ↔ FIGI ↔ ISIN ↔ SEDOL | Do this in week one. It is what lets sources 1–4 talk to each other. |
| + | **BoE IADB** | GBP/USD, Bank Rate | One CSV URL, no key. You need FX the moment you rank London against New York. |

---

## Price data

### Stooq — `quantlab.providers.stooq`

- **Free**: yes. No key, no registration, no symbol cap.
- **Coverage**: US (`.us`) and UK (`.uk`) from the same endpoint. Daily history 30+ years
  on US names. Intraday is capped (~1,400 hourly bars, ~2,000 5-minute bars).
- **Endpoint**: `https://stooq.com/q/d/l/?s={symbol}&i=d`
- **Limits**: none published. That is not permission — it is an absence of policy. The
  default limiter here is 2 req/s as a courtesy.
- **Licence**: no published terms. Personal research only; do not redistribute.
- **Gotchas**: thin AIM names have gaps and occasional bad ticks. `pandas-datareader`'s
  Stooq reader truncates to ~5 years — hit the CSV URL directly, which is what this
  adapter does. A bulk US ZIP exists at `stooq.com/db/h`; **a UK bulk equivalent is
  unverified.**

### Yahoo Finance — `quantlab.providers.yahoo`

- **Free**: yes, via `pip install 'quantlab[yahoo]'`. Pin the version — `yfinance` went
  0.2.x → 1.x during 2025/26 and the API moved.
- **Coverage**: best free LSE coverage (`.L`), including AIM. Plus sector, industry and
  shares outstanding, and — uniquely among free sources — **UK dividends and splits**.
- **Limits**: undocumented and changing. Community reports put the 429 threshold around
  360 requests/hour and ~950 tickers in a burst. The adapter uses Yahoo's genuine bulk
  download endpoint in chunks of 200 and backs off exponentially.
- **Licence**: unofficial endpoint. Yahoo's terms describe personal use only. No
  redistribution, no commercial use, no SLA.
- **Design for failure.** `quantlab.data.load` retries failed symbols against the next
  provider, so a Yahoo outage degrades to Stooq rather than taking the pipeline down.

### Not worth building against (checked, rejected)

| Source | Free tier in 2026 | Verdict |
|---|---|---|
| Financial Modeling Prep | 250 calls/day **but symbol-limited to ~87 hard-coded US tickers** | Universe cut, not a rate cut. Unusable. |
| Alpha Vantage | 25 calls/day. LSE via `.LON` | 5,000 names = 200 days per refresh. Reconciliation oracle only. |
| EODHD | 20 calls/day, **1-year history** on free | Non-viable. Demo key is a 6-ticker whitelist. |
| Tiingo | 50/hr, 1,000/day, **500 unique symbols/month**; no LSE | Hard structural cap. Excellent if you pay ($30/mo, history from 1962). |
| Polygon (**now "Massive"**) | 5 calls/min, 2 years, EOD, **US only** | Rebranded in early 2026; `api.polygon.io` still works. No LSE. |
| Twelve Data | 800 credits/day but US equities only on free | LSE needs the $79/mo tier. |
| Marketstack | **100 requests/month** | A toy. |
| Nasdaq Data Link | Free equity data effectively dead; `WIKI/PRICES` unmaintained since 2018 | Docs site carried a 2026-08-31 retirement notice. Use FRED for macro instead. |

---

## Fundamentals

### SEC EDGAR (US) — `quantlab.providers.sec_edgar`

The best free financial data source that exists, and the only one here that is public
domain and unambiguously safe commercially.

- **No API key.** Two hard rules: **10 requests/second**, and a **User-Agent containing a
  contact email** (`SEC_USER_AGENT='Your Name you@example.com'`). Unidentified clients get
  IP-blocked.
- **Endpoints**
  - `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` — everything one filer ever tagged
  - `data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/CY{period}.json` — **one concept,
    one period, every filer, one request**. This is how 5,000 names becomes tractable.
  - `sec.gov/files/company_tickers.json` — ticker → CIK master
  - Nightly bulk ZIPs of companyfacts and submissions — use these instead of per-CIK loops
  - `sec.gov/files/dera/data/financial-statement-data-sets/{YYYY}q{Q}.zip` — flattened
    face financials, 2009 to present
- **Coverage**: US registrants only. UK companies appear only as 20-F/40-F foreign private
  issuers — a handful of dual-listings.
- **Note**: `efts.sec.gov` (full-text search) is undocumented by the SEC. Its stability and
  rate policy are **unverified**; do not build a pipeline on it.
- **Storage**: facts land in the Postgres `fundamentals` table (migration 004) — one row per
  (instrument, taxonomy, tag, unit, period, filing), point-in-time by `filed_at`. Two jobs,
  both needing `SEC_USER_AGENT` in `.env`:
  - `make map-sec-tickers` (`quantlab map-sec-tickers`) — matches catalog `.US` instruments
    against `company_tickers.json` (case- and class-share-tolerant: `BRK.B` → `BRK-B`), writes
    `instruments.cik` (zero-padded) plus a `symbol_map` row under `source='sec_edgar'`, and
    reports matched/unmatched counts. Resumable via `--only-missing` (default).
  - `make ingest-sec-fundamentals` (`quantlab ingest-sec-fundamentals [--limit N] [--all]`) —
    pulls `companyfacts` per CIK-bound instrument (≤10 req/s via the shared limiter), flattens
    every `facts.<taxonomy>.<tag>.units.<unit>[]` entry into `fundamentals` with
    `provider='sec_edgar'`, `accession=accn`, `filed_at=filed`. Idempotent (the accession is in
    the row identity), committed in 25-instrument chunks, resumable.

### Companies House (UK) — `quantlab.providers.companies_house`

The only free, official, bulk UK fundamentals source, and underrated — it is missing from
most "free financial data" lists.

- **Free key** from `developer.company-information.service.gov.uk`. **600 requests per
  5-minute window** (2 req/s sustained).
- **Free Accounts Data Product** (`download.companieshouse.gov.uk/en_accountsdata.html`):
  daily ZIPs of electronically filed accounts as iXBRL, no key. Covers ~75% of filings.
  **Daily files are kept for 60 days only** — backfill early and keep your own archive.
- **Honest limitations**, because they shape what you can build:
  - Many LSE issuers are incorporated in Jersey, Guernsey, Ireland or the Isle of Man and
    are simply not in Companies House.
  - **Most large PLCs file their accounts at CH as scanned PDFs, not iXBRL** — verified
    across the FTSE core in 2026-09: every mapped FTSE-100 name's filing history is
    100% `application/pdf`. iXBRL coverage is concentrated in smaller companies filing
    via accounting software. The ingest checks the document metadata's resource list and
    skips PDF-only filings (logged per company), so `ingest-ch-fundamentals` yields
    facts only where iXBRL actually exists. UK large-cap fundamentals effectively need a
    different source (or PDF extraction, deferred).
  - Accounts follow a statutory calendar, not a market reporting calendar. They lag and are
    coarser than US quarterly filings.
  - **Nothing in the data carries a ticker.** You build the company-number → SEDOL/ISIN →
    ticker bridge yourself. OpenFIGI does the second hop.
- **Licence**: Crown copyright, normally Open Government Licence. The download page itself
  only says "provided free of charge and is not supported" — **confirm before commercial
  use (unverified).**
- **Storage**: parsed iXBRL facts share the `fundamentals` table with SEC data
  (`provider='companies_house'`), keyed by `company_number` via
  `instruments.company_number` — no ticker bridge table is needed. `filed_at` is the
  filing-history date, the only honest point-in-time anchor the API gives.
- **The ticker bridge exists**: `make map-ch-companies` (`quantlab map-ch-companies
  [--limit N] [--all]`) searches `/search/companies` once per `.LON` instrument using the
  OpenFIGI name recorded by `make map-identifiers` (Bloomberg decorations like `/THE` and
  `-DI` are stripped first), so **run `map-identifiers` before `map-ch-companies`**.
  Matching is deliberately conservative: both sides are normalized (case, punctuation —
  including CH's dotted "P.L.C." form — a leading THE, trailing PLC/LIMITED/LTD legal
  forms), and a match is accepted only as an exact normalized-name hit on a single
  **active** company, or a HOLDINGS/GROUP-stripped hit when the search returned exactly
  one active candidate. Ambiguous multi-hits go to the report's review list and are never
  written; an existing `company_number` is never overwritten. Search responses are cached
  30 days, so re-runs are free. Known gaps beyond the Jersey/Guernsey/IoM/Ireland
  incorporation hole (Glencore, WPP, Pershing Square…): instruments with no recorded name
  at all are skipped, and vendor-name abbreviations ("SAINSBURY (J) PLC", "SCOTTISH
  MORTGAGE INV TR PLC", truncated "INTERCONTINENTAL HOTELS GROU") do not match the
  registered title — those land in the unresolved list for manual mapping.
  `make ingest-ch-fundamentals` (`quantlab ingest-ch-fundamentals [--limit N]`, needs
  `COMPANIES_HOUSE_API_KEY` in `.env`) walks each company's filing history and parses
  every accounts document for the `UK_TAGS` concepts. Two documented gaps: `unit` stays
  empty (the regex parser does not resolve `unitRef` to a currency — values are in the
  company's presentation currency), and `period_end` comes from the document's
  `EndDateForPeriodCoveredByReport`/`BalanceSheetDate` tag, falling back to the filing
  date with `meta.period_end_assumed` when the tag is absent. Resolving iXBRL contexts
  properly (periods, dimensions, currencies) is deferred — swap in `arelle` if that
  precision ever matters.

---

## Identifiers, FX and macro

### OpenFIGI — `quantlab.providers.openfigi`

Free, no usage limits stated. An optional free key raises `/v3/mapping` from 25 req/min ×
10 jobs to 25 req/6s × 100 jobs — about 25,000 mappings per minute, so a 5,000-name
universe resolves in seconds.

Accepts `TICKER`, `ID_ISIN`, `ID_SEDOL`, `ID_CUSIP` and more. **One asymmetry worth
designing around**: the response carries FIGI, ticker, name and exchange code — *not*
ISIN. So ISIN/SEDOL → FIGI → ticker works; ticker → ISIN needs another source.

`make map-identifiers` maps the whole warehouse catalog keyless: FIGI → `instruments.figi`
and `symbol_map` (source `openfigi`), the rest of the payload → `meta.openfigi`. It is
resumable (`--only-missing` is the default) and skips synthetic/macro pseudo-instruments.

### Bank of England IADB — `quantlab.providers.boe`

Free, keyless, one documented CSV endpoint, up to **300 series per request**. Gives you
Bank Rate, GBP/USD and GBP/EUR daily spot, gilt yields. No documented rate limit — be
polite. Licence not stated on the help page (**unverified**), though BoE statistics are
generally freely reusable with attribution.

### FRED — `quantlab.providers.fred`

Free key required (`FRED_API_KEY` in `.env`). US macro: yield curve, HY credit spreads,
VIX, real rates, dollar index. **Published rate limit: not stated on the official pages
(unverified)** — the widely cited 120/min is third-party. Much of FRED is *redistributed*
third-party data (OECD, BIS) whose own terms still apply.

`make ingest-fred` (`quantlab ingest-macro --provider fred`) loads the default set as
pseudo-instrument bars, same bridge as the BoE series:

| FRED code | Pseudo-symbol | Series |
|---|---|---|
| `VIXCLS` | `VIX.FRED` | CBOE Volatility Index, close |
| `DGS10` | `UST10Y.FRED` | 10-Year Treasury constant maturity |
| `DGS2` | `UST2Y.FRED` | 2-Year Treasury constant maturity |
| `BAMLH0A0HYM2` | `HYSPREAD.FRED` | ICE BofA US High Yield OAS |
| `DFII10` | `REAL10Y.FRED` | 10-Year TIPS (real) yield |
| `DTWEXBGS` | `DOLLARIDX.FRED` | Nominal broad US dollar index |

Override with `--series CODE:SYMBOL` (repeatable). Note `DFII10` went negative in
2020–21: bars must be strictly positive, so those days are quarantined into
`ingest_rejects` and the run closes "partial" — expected, not a failure.

---

## Universe lists

### US — `quantlab.universe.nasdaqtrader`

`nasdaqtrader.com/dynamic/symdir/otherlisted.txt` carries NYSE, NYSE American, NYSE Arca
and CBOE; `nasdaqlisted.txt` carries Nasdaq. Pipe-delimited, daily, free. **Whether these
still resolve in 2026 is unverified** — confirm before relying on them. `nyse.com`'s own
listings directory is a JavaScript UI with no export. SEC's `company_tickers.json` is an
excellent official fallback for a US ticker master.

The files include test issues, ETFs, warrants and preferreds. Filtering is on by default —
a "universe" full of warrants will quietly wreck your cross-sectional statistics.

### UK — `quantlab.universe.lse`

**This is the weakest link and the highest-priority thing for you to resolve.** The LSE
reports hub (`londonstockexchange.com/reports`) is a JavaScript application; the old
`instrumentlist.xls` URL still appears in search indexes but **could not be verified as
resolving in 2026**. LSEG sells instrument reference data as a product.

The adapter therefore tries three routes and tells you which it used:

1. `path=` — a file you downloaded yourself from the reports page. Manual, boring, and by
   far the most reliable. **Recommended for production.**
2. `url=` — a direct link, if you find a working one.
3. A bundled ~95-name FTSE core list, so the package works out of the box.

If you only need the liquid end of the market, route 3 is honestly fine — the long AIM tail
is exactly where free price data is least trustworthy anyway.

---

## Alternative data (all free, all official)

| Source | What | Cadence | Notes |
|---|---|---|---|
| **FINRA short volume** | US daily short sale volume | Same day by 18:00 ET | **Ingested** — see below. Short *volume*, not short interest — 40–50% is normal and mostly market making. Read the z-score, not the level. |
| **FCA net short positions** | UK disclosed net shorts | Daily from 12:00, **T+2** | **Ingested** — see below. 0.2% disclosure threshold. This *is* short interest and it is genuinely informative. |
| **SEC Form 3/4/5** | US insider transactions | Quarterly bulk ZIPs; daily via EDGAR index | Buys inform, sales are mostly noise. Clusters of distinct buyers beat individuals. |
| **RNS** (UK) | Company announcements, PDMR dealings | Continuous | **No free official API.** `investegate.co.uk` and `lse.co.uk/rns` are free to read but are scraping targets, and RNS content is LSEG-copyrighted. |
| **ESG** | — | — | **No free, machine-readable, broad-universe source exists.** Drop it from v1. |

### FINRA short volume — `quantlab.providers.finra`

- **Free**: yes. Keyless, no registration, one flat file per trading day at
  `cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`. No published
  rate limit; the limiter here is 2 req/s as a courtesy, and the files are
  one per day anyway.
- **File shape**: `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`,
  ~12,300 symbols, with a bare record-count line as the footer (the parser skips
  it). Class shares are slash-spelled (`BRK/A` → catalog `BRK.B.US`); volumes can
  be fractional.
- **Availability**: verified 2026-09 — files reach back to ~2018-08-01 on the CDN.
  An absent file (weekend, market holiday, not yet published) answers **HTTP 403,
  not 404**, and the provider treats that as `DataUnavailable`, never an error.
- **Storage**: the Postgres `fundamentals` table, `provider='finra'`, tags
  `short_volume` / `short_exempt_volume` / `total_volume`, unit `shares`,
  `period_end` = `filed_at` = trade date (published by 18:00 ET that day),
  `accession='CNMSshvol-YYYYMMDD'`, so a re-ingest of a day is an ON CONFLICT
  no-op. FINRA symbols not in the catalog are skipped and counted in the run
  report. Nothing goes to ClickHouse — this is small relational data, not bars.
- `make ingest-finra-shorts` (`quantlab ingest-finra-shorts [--date YYYYMMDD |
  --start --end] [--limit N]`): one request per weekday, commits per day, default
  range the last 31 days.

### FCA net short positions — `quantlab.providers.fca`

- **Free**: yes. Keyless, one daily-refreshed workbook:
  `fca.org.uk/publication/data/short-positions-daily-update.xlsx` — the *entire*
  disclosure history since 2013 (~109k rows verified 2026-09), columns
  `Position Holder | Name of Share Issuer | ISIN | Net Short Position (%) |
  Position Date`. Reading it needs openpyxl (`pip install quantlab[excel]`; the
  ingest image carries it). The old `api.data.fca.org.uk` host no longer resolves;
  the static xlsx is the stable endpoint.
- **Freshness caveat**: despite the "daily update" name, the file pulled on
  2026-09-20 contained no position dated after **2026-07-09** (~10 weeks stale).
  Check `max(period_end)` after each pull before trusting the recent end.
- **Honest gaps**, because they shape what you can build:
  - The file is ISIN-keyed and the catalog has **no ISINs** (OpenFIGI does not
    return them), so issuers are bridged by conservative normalized-name
    matching — the same rules as `map_ch_companies`. A normalized name claimed
    by two catalog instruments matches nothing; unmatched issuers are counted
    in the run report, never guessed.
  - Each row is one **holder's** position. The issuer-level net short is the
    sum over holders at read time.
  - A 0.0% row is a position that fell below the disclosure threshold — kept,
    not dropped; it is information.
- **Storage**: `fundamentals`, `provider='fca'`, tag `net_short_position_pct`,
  unit `pct`, `period_end` = position date, `filed_at` = position date + 2
  business days (the T+2 publication basis), `accession` = holder name (the
  disclosure identity — re-pulls are no-ops), ISIN/holder/issuer name in `meta`.
- `make ingest-fca-shorts` (`quantlab ingest-fca-shorts [--limit N]`): a single
  fetch, committed in 10k-row chunks.

### The UK/US asymmetry

Worth internalising before designing a strategy that assumes symmetry:

| | US | UK |
|---|---|---|
| Fundamentals | SEC XBRL, quarterly, public domain | Companies House iXBRL, statutory calendar, ~10–20% of LSE issuers missing |
| Insider dealings | Form 4 bulk datasets, structured | RNS free text only |
| Short data | Short *volume*, daily | Short *interest*, daily, T+2 — **better than the US** |
| Corporate actions | Well covered free | Yahoo `.actions` only; expect missed special dividends |
| Price licensing | Clean (SEC public domain for filings) | Nothing free is licensed |

---

## Two traps that will cost you money

**1. The pence problem.** Most LSE lines quote in GBX (pence), some in GBP, a few in USD
or EUR. Mixing them produces price ratios off by 100× and quietly poisons every
cross-sectional factor downstream. `quantlab.fx` detects and normalises this, and
`docs/ARCHITECTURE.md` explains the rule. Do not skip it.

**2. Survivorship bias.** Every free source listed here gives you *currently listed*
companies. Delisted names are gone. Any backtest built on a universe fetched today is
measuring the performance of companies that survived — which is not a real strategy. There
is no free fix. Partial mitigations: SEC `company_tickers.json` history, Companies House
dissolved-company records, and archiving your own universe snapshots from day one.
`quantlab universe <name> --out snapshot.csv` on a daily schedule costs nothing and in
three years you will have something no free source sells. For the warehouse itself,
`make universe-snapshot` (`quantlab universe-snapshot <name>`) archives the currently
ingested universe — every real instrument with bars, excluding synthetic and macro
pseudo-instruments — into the append-only `universe_snapshots`/`universe_members` tables.

---

## Offline: synthetic data

When no source is reachable — or you want a reproducible fixture — the warehouse can be
seeded with deterministic synthetic bars: `make seed-warehouse` (or `quantlab
seed-synthetic`). `quantlab.synthetic.generate_bars` is a pure function of
(symbol, start, end, seed) with a sha256-derived PCG64 stream and no wall clock, so the
seeded dataset is byte-identical across machines and runs. Details and guarantees are in
the "Synthetic data" section of `docs/STORAGE.md`.

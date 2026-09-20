"""Command line interface."""
from __future__ import annotations

import argparse
import json
import logging
import sys

import pandas as pd


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def cmd_list(args) -> int:
    from .registry import DERIVED, INDICATORS, PROVIDERS, UNIVERSES, load_plugins

    load_plugins()
    kinds = {"indicators": INDICATORS, "derived": DERIVED, "providers": PROVIDERS, "universes": UNIVERSES}
    chosen = kinds if args.kind == "all" else {args.kind: kinds[args.kind]}

    if args.json:
        from .registry import describe

        print(json.dumps(describe(), indent=2))
        return 0

    for label, reg in chosen.items():
        print(f"\n{label.upper()} ({len(reg)})")
        print("-" * 72)
        for name, obj in reg.items():
            spec = getattr(obj, "spec", None)
            if spec is not None:
                if args.tag and args.tag not in spec.tags:
                    continue
                outs = ",".join(spec.resolved_outputs())
                params = " ".join(f"{k}={v}" for k, v in spec.params.items())
                doc = (spec.description or "").split("\n")[0][:60]
                print(f"  {name:<24} {outs:<34} {params}")
                if doc:
                    print(f"  {'':<24} {doc}")
            else:
                note = getattr(obj, "licence_note", "")
                key = " [needs key]" if getattr(obj, "requires_key", False) else ""
                print(f"  {name:<24}{key}")
                if note:
                    print(f"  {'':<24} {note[:90]}")
    return 0


def cmd_sources(args) -> int:
    from .ratelimit import DEFAULT_LIMITS
    from .registry import PROVIDERS, load_plugins

    load_plugins()
    print(f"{'source':<18} {'key':<5} {'rate':<26} licence note")
    print("-" * 110)
    for name, cls in PROVIDERS.items():
        limit = DEFAULT_LIMITS.get(name)
        rate = f"{limit.rate * 60:.1f}/min" if limit else "-"
        if limit and limit.daily_cap:
            rate += f", cap {limit.daily_cap}/day"
        key = "yes" if getattr(cls, "requires_key", False) else "no"
        print(f"{name:<18} {key:<5} {rate:<26} {getattr(cls, 'licence_note', '')[:60]}")
    return 0


def cmd_fetch(args) -> int:
    from .data import load, save_panel

    panel, ctx = load(
        symbols=args.symbols or None,
        universe=args.universe or "",
        start=args.start,
        end=args.end or "",
        frequency=args.frequency,
        providers=args.providers,
        provider_options=_parse_provider_options(args.provider_option),
        return_context=True,
    )
    print(f"{len(panel)} rows, {panel.index.get_level_values('symbol').nunique()} symbols", file=sys.stderr)
    missing = ctx.extras.get("missing", [])
    if missing:
        print(f"no data for {len(missing)}: {', '.join(missing[:10])}", file=sys.stderr)
    if args.out:
        print(save_panel(panel, args.out))
    else:
        print(panel.tail(args.tail).to_string())
    return 0


def cmd_compute(args) -> int:
    from .data import load, load_panel, save_panel
    from .engine import Context, FeatureEngine

    if args.panel:
        panel, ctx = load_panel(args.panel), Context()
    else:
        panel, ctx = load(
            symbols=args.symbols or None,
            universe=args.universe or "",
            start=args.start,
            end=args.end or "",
            providers=args.providers,
            provider_options=_parse_provider_options(args.provider_option),
            return_context=True,
        )

    engine = FeatureEngine(ctx, on_error="warn")
    result, report = engine.compute(panel, args.features, report=True)
    print(report.summary(), file=sys.stderr)
    if args.out:
        print(save_panel(result, args.out))
    else:
        print(result.tail(args.tail).to_string())
    return 0


def cmd_run(args) -> int:
    from .config import PipelineConfig
    from .data import run_pipeline, save_panel

    cfg = PipelineConfig.from_yaml(args.config)
    result, report = run_pipeline(cfg, report=True)
    print(report.summary(), file=sys.stderr)
    out = args.out or cfg.output
    if out:
        print(save_panel(result, out))
    else:
        print(result.tail(args.tail).to_string())
    return 0


def cmd_universe(args) -> int:
    from .data import get_universe

    uni = get_universe(args.name, **_parse_kv(args.param))
    frame = uni.to_frame()
    print(f"{len(frame)} securities from {args.name}", file=sys.stderr)
    if getattr(uni, "source_used", ""):
        print(f"source: {uni.source_used}", file=sys.stderr)
    if args.out:
        frame.to_csv(args.out)
        print(args.out)
    else:
        print(frame.head(args.tail).to_string())
    return 0


def cmd_doctor(args) -> int:
    """Check the environment: plugins loaded, keys present, sources reachable."""
    from .config import settings
    from .registry import describe, load_errors, load_plugins

    load_plugins()
    st = settings()
    inv = describe()
    print("plugins")
    for kind, items in inv.items():
        print(f"  {kind:<12} {len(items)}")
    errs = load_errors()
    if errs:
        print("\nplugin load errors")
        for where, msg in errs:
            print(f"  {where}: {msg}")

    print("\ncredentials (all optional, all free)")
    for label, value, why in (
        ("SEC_USER_AGENT", st.user_agent if "@" in st.user_agent else "", "required by SEC EDGAR"),
        ("FRED_API_KEY", st.fred_api_key, "US macro series"),
        ("OPENFIGI_API_KEY", st.openfigi_api_key, "10x identifier mapping throughput"),
        ("COMPANIES_HOUSE_API_KEY", st.companies_house_key, "UK fundamentals"),
    ):
        mark = "set" if value else "not set"
        print(f"  {label:<26} {mark:<9} {why}")

    print(f"\npaths\n  home   {st.root}\n  cache  {st.cache_dir}\n  data   {st.data_dir}")
    print(f"  offline mode: {st.offline}")
    return 0


def cmd_migrate(args) -> int:
    from . import store

    with store.session(args.db_url) as conn, store.ch_session(args.ch_url) as client:
        applied = store.migrate_all(conn, client)
        for half, versions in applied.items():
            print(f"{half}: " + (", ".join(versions) if versions else "up to date"))
        print(f"\ncatalog schema {store.current_version(conn)}")
        print(f"bars schema    {store.ch_current_version(client)}")
    return 0


def cmd_ingest(args) -> int:
    from . import store

    if not args.symbols and not args.universe:
        raise SystemExit("ingest needs symbols or --universe")

    with store.session(args.db_url) as conn, store.ch_session(args.ch_url) as client:
        if not args.no_migrate:
            store.migrate_all(conn, client)

        report = store.ingest_prices(
            conn,
            client,
            args.symbols or None,
            start=args.start,
            end=args.end,
            frequency=args.frequency,
            providers=args.providers,
            provider_options=_parse_provider_options(args.provider_option),
            universe=args.universe,
            universe_params=_parse_kv(args.param),
            snapshot_date=args.snapshot_date or None,
            max_workers=args.max_workers,
        )
        print(report.summary())

        if args.corporate_actions:
            symbols = args.symbols or store.list_symbols(conn)
            actions = store.ingest_corporate_actions(
                conn, symbols, start=args.start, end=args.end,
                provider=args.actions_provider,
            )
            print(actions.summary())

        if args.optimize:
            # Pay the ReplacingMergeTree merge now rather than on every read.
            store.optimize(client)

    # A run that wrote nothing is a failure the shell should see.
    return 0 if report.status in ("ok", "partial") else 1


def cmd_seed_synthetic(args) -> int:
    from . import store
    from .synthetic import DEFAULT_UNIVERSE

    if not 1 <= args.symbols <= len(DEFAULT_UNIVERSE):
        raise SystemExit(f"--symbols must be 1..{len(DEFAULT_UNIVERSE)}")

    with store.session(args.db_url) as conn, store.ch_session(args.ch_url) as client:
        if not args.no_migrate:
            store.migrate_all(conn, client)

        report = store.seed_warehouse(
            conn,
            client,
            DEFAULT_UNIVERSE[: args.symbols],
            start=args.start,
            end=args.end,
            seed=args.seed or None,
        )
        print(report.summary())

        if args.optimize:
            # Pay the ReplacingMergeTree merge now rather than on every read.
            store.optimize(client)

    return 0 if report.status in ("ok", "partial") else 1


def cmd_ingest_macro(args) -> int:
    from . import store
    from .store.macro import parse_series_args

    try:
        mapping = parse_series_args(args.series)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    with store.session(args.db_url) as conn, store.ch_session(args.ch_url) as client:
        if not args.no_migrate:
            store.migrate_all(conn, client)

        report = store.ingest_macro_series(
            conn,
            client,
            mapping,
            start=args.start,
            end=args.end,
        )
        print(report.summary())

        if args.optimize:
            # Pay the ReplacingMergeTree merge now rather than on every read.
            store.optimize(client)

    return 0 if report.status in ("ok", "partial") else 1


def cmd_map_identifiers(args) -> int:
    from . import store

    # Catalog-only: identifier mappings live in Postgres, not ClickHouse.
    with store.session(args.db_url) as conn:
        if not args.no_migrate:
            store.migrate(conn)

        report = store.map_identifiers(
            conn,
            limit=args.limit,
            only_missing=args.only_missing,
        )
        print(report.summary())

    return 0 if report.status in ("ok", "partial") else 1


def cmd_coverage(args) -> int:
    from . import store

    with store.session(args.db_url) as conn, store.ch_session(args.ch_url) as client:
        frame = store.coverage(conn, client, frequency=args.frequency)
        if frame.empty:
            print("store is empty -- run `quantlab ingest` first")
            return 0
        print(f"coverage ({len(frame)} instruments)")
        print(frame.to_string(index=False))
        print(f"\ntotal bars: {int(frame['bars'].sum()):,}")

        stats = store.storage_stats(client)
        if stats is not None and not stats.empty:
            print("\nstorage (ClickHouse partitions)")
            print(stats.to_string(index=False))

        stale = store.stale_runs(conn)
        if not stale.empty:
            # Bars land in ClickHouse before the run closes in Postgres, so an
            # interrupted ingest leaves a run open. Those counts are unverified.
            print(f"\nWARNING: {len(stale)} ingest run(s) never finished")
            print(stale.to_string(index=False))

        if args.runs:
            history = store.run_history(conn, limit=args.runs)
            print("\nrecent ingest runs")
            print(history.to_string(index=False))
    return 0


def cmd_replay_publish(args) -> int:
    import os

    from . import store
    from .streaming import DEFAULT_TOPIC, create_producer, publish_replay

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("replay-publish needs --symbols (comma-separated)")

    brokers = args.brokers or os.environ.get("QUANTLAB_KAFKA_BROKERS", "")
    if not brokers.strip():
        raise SystemExit("no brokers: pass --brokers or set QUANTLAB_KAFKA_BROKERS")
    topic = args.topic or os.environ.get("QUANTLAB_KAFKA_TOPIC", "") or DEFAULT_TOPIC

    with store.session(args.db_url) as conn, store.ch_session(args.ch_url) as client:
        producer = create_producer(brokers)
        try:
            report = publish_replay(
                conn,
                client,
                producer,
                symbols,
                args.start,
                args.end,
                topic=topic,
                pace_ms=args.pace_ms,
            )
        finally:
            producer.close()
    print(report.summary())
    return 0


def _parse_provider_options(pairs: list[str] | None) -> dict:
    """--provider-option csv:directory=/data -> {"csv": {"directory": "/data"}}"""
    out: dict[str, dict] = {}
    for item in pairs or []:
        if ":" not in item or "=" not in item:
            raise SystemExit(f"--provider-option expects provider:key=value, got {item!r}")
        prov, rest = item.split(":", 1)
        out.setdefault(prov, {}).update(_parse_kv([rest]))
    return out


def _parse_kv(pairs: list[str] | None) -> dict:
    out: dict[str, object] = {}
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"--param expects key=value, got {item!r}")
        k, v = item.split("=", 1)
        if v.lower() in {"true", "false"}:
            out[k] = v.lower() == "true"
        else:
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quantlab", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    lst = sub.add_parser("list", help="list registered plugins")
    lst.add_argument("kind", nargs="?", default="all",
                     choices=["all", "indicators", "derived", "providers", "universes"])
    lst.add_argument("--tag", default="")
    lst.add_argument("--json", action="store_true")
    lst.set_defaults(func=cmd_list)

    src = sub.add_parser("sources", help="show data sources, limits and licences")
    src.set_defaults(func=cmd_sources)

    f = sub.add_parser("fetch", help="download bars")
    f.add_argument("symbols", nargs="*")
    f.add_argument("--universe", default="")
    f.add_argument("--start", default="2020-01-01")
    f.add_argument("--end", default="")
    f.add_argument("--frequency", default="1d")
    f.add_argument("--providers", nargs="+", default=["stooq", "yahoo"])
    f.add_argument("--provider-option", action="append",
                   help="provider:key=value, e.g. csv:directory=/data, repeatable")
    f.add_argument("--out", default="")
    f.add_argument("--tail", type=int, default=20)
    f.set_defaults(func=cmd_fetch)

    c = sub.add_parser("compute", help="compute features")
    c.add_argument("--features", nargs="+", required=True)
    c.add_argument("--symbols", nargs="*")
    c.add_argument("--universe", default="")
    c.add_argument("--panel", default="", help="read a saved parquet panel instead of fetching")
    c.add_argument("--start", default="2020-01-01")
    c.add_argument("--end", default="")
    c.add_argument("--providers", nargs="+", default=["stooq", "yahoo"])
    c.add_argument("--provider-option", action="append",
                   help="provider:key=value, repeatable")
    c.add_argument("--out", default="")
    c.add_argument("--tail", type=int, default=20)
    c.set_defaults(func=cmd_compute)

    r = sub.add_parser("run", help="run a YAML pipeline")
    r.add_argument("config")
    r.add_argument("--out", default="")
    r.add_argument("--tail", type=int, default=20)
    r.set_defaults(func=cmd_run)

    u = sub.add_parser("universe", help="resolve a universe to a list of securities")
    u.add_argument("name")
    u.add_argument("--param", action="append", help="key=value, repeatable")
    u.add_argument("--out", default="")
    u.add_argument("--tail", type=int, default=25)
    u.set_defaults(func=cmd_universe)

    d = sub.add_parser("doctor", help="check plugins, keys and paths")
    d.set_defaults(func=cmd_doctor)

    # -- Postgres system of record ----------------------------------------
    m = sub.add_parser("migrate", help="apply pending migrations to catalog and bars")
    m.add_argument("--db-url", default="", help="Postgres catalog; overrides $QUANTLAB_DB_URL")
    m.add_argument("--ch-url", default="", help="ClickHouse bars; overrides $QUANTLAB_CH_URL")
    m.set_defaults(func=cmd_migrate)

    i = sub.add_parser("ingest", help="load historical bars into Postgres")
    i.add_argument("symbols", nargs="*")
    i.add_argument("--universe", default="")
    i.add_argument("--param", action="append", help="universe key=value, repeatable")
    i.add_argument("--start", default="2015-01-01")
    i.add_argument("--end", default="")
    i.add_argument("--frequency", default="1d")
    i.add_argument("--providers", nargs="+", default=["stooq", "yahoo"])
    i.add_argument("--provider-option", action="append",
                   help="provider:key=value, repeatable")
    i.add_argument("--db-url", default="", help="Postgres catalog; overrides $QUANTLAB_DB_URL")
    i.add_argument("--ch-url", default="", help="ClickHouse bars; overrides $QUANTLAB_CH_URL")
    i.add_argument("--optimize", action="store_true",
                   help="force the ClickHouse merge after loading (worth it after a backfill)")
    i.add_argument("--snapshot-date", default="",
                   help="universe snapshot date (default: today)")
    i.add_argument("--max-workers", type=int, default=None)
    i.add_argument("--no-migrate", action="store_true",
                   help="skip the automatic migrate step")
    i.add_argument("--corporate-actions", action="store_true",
                   help="also pull dividends and splits")
    i.add_argument("--actions-provider", default="yahoo",
                   help="provider for corporate actions (default: yahoo)")
    i.set_defaults(func=cmd_ingest)

    s = sub.add_parser(
        "seed-synthetic",
        help="seed the warehouse with deterministic synthetic bars (no network)",
    )
    s.add_argument("--symbols", type=int, default=25,
                   help="number of synthetic instruments to seed (max 25)")
    s.add_argument("--start", default="2022-01-01")
    s.add_argument("--end", default="2025-12-31")
    s.add_argument("--seed", default="",
                   help="extra seed salt; identical inputs give byte-identical bars")
    s.add_argument("--db-url", default="", help="Postgres catalog; overrides $QUANTLAB_DB_URL")
    s.add_argument("--ch-url", default="", help="ClickHouse bars; overrides $QUANTLAB_CH_URL")
    s.add_argument("--optimize", action="store_true",
                   help="force the ClickHouse merge after loading")
    s.add_argument("--no-migrate", action="store_true",
                   help="skip the automatic migrate step")
    s.set_defaults(func=cmd_seed_synthetic)

    im = sub.add_parser(
        "ingest-macro",
        help="load BoE macro series (FX, Bank Rate, gilts, M4) as pseudo-instrument bars",
    )
    im.add_argument("--start", default="2010-01-01")
    im.add_argument("--end", default="")
    im.add_argument("--series", action="append",
                    help="CODE:SYMBOL, e.g. XUDLUSS:GBPUSD.BOE, repeatable; "
                         "default: the five BoE COMMON_SERIES")
    im.add_argument("--db-url", default="", help="Postgres catalog; overrides $QUANTLAB_DB_URL")
    im.add_argument("--ch-url", default="", help="ClickHouse bars; overrides $QUANTLAB_CH_URL")
    im.add_argument("--optimize", action="store_true",
                    help="force the ClickHouse merge after loading")
    im.add_argument("--no-migrate", action="store_true",
                    help="skip the automatic migrate step")
    im.set_defaults(func=cmd_ingest_macro)

    mid = sub.add_parser(
        "map-identifiers",
        help="map catalog instruments to OpenFIGI identifiers (keyless; resumable)",
    )
    mid.add_argument("--limit", type=int, default=None,
                     help="map at most N instruments this run")
    mid.add_argument("--only-missing", dest="only_missing", action="store_true", default=True,
                     help="only instruments without a FIGI yet (default; makes re-runs resume)")
    mid.add_argument("--all", dest="only_missing", action="store_false",
                     help="re-map every eligible instrument, refreshing existing FIGIs")
    mid.add_argument("--db-url", default="", help="Postgres catalog; overrides $QUANTLAB_DB_URL")
    mid.add_argument("--no-migrate", action="store_true",
                     help="skip the automatic migrate step")
    mid.set_defaults(func=cmd_map_identifiers)

    rp = sub.add_parser(
        "replay-publish",
        help="publish warehouse bars to a Kafka topic as a chronological event stream",
    )
    rp.add_argument("--symbols", required=True,
                    help="comma-separated canonical symbols, e.g. ZX1.US,ZX2.US")
    rp.add_argument("--start", required=True, help="first session date, YYYY-MM-DD")
    rp.add_argument("--end", required=True, help="last session date, YYYY-MM-DD")
    rp.add_argument("--topic", default="",
                    help="Kafka topic (default: $QUANTLAB_KAFKA_TOPIC or quantlab.bars)")
    rp.add_argument("--brokers", default="",
                    help="bootstrap servers (default: $QUANTLAB_KAFKA_BROKERS)")
    rp.add_argument("--pace-ms", type=int, default=0,
                    help="milliseconds to wait between dates, simulating realtime")
    rp.add_argument("--db-url", default="", help="Postgres catalog; overrides $QUANTLAB_DB_URL")
    rp.add_argument("--ch-url", default="", help="ClickHouse bars; overrides $QUANTLAB_CH_URL")
    rp.set_defaults(func=cmd_replay_publish)

    cov = sub.add_parser("coverage", help="what is in the store and where it came from")
    cov.add_argument("--frequency", default="1d")
    cov.add_argument("--db-url", default="", help="Postgres catalog; overrides $QUANTLAB_DB_URL")
    cov.add_argument("--ch-url", default="", help="ClickHouse bars; overrides $QUANTLAB_CH_URL")
    cov.add_argument("--runs", type=int, default=5,
                     help="also show the N most recent ingest runs (0 to hide)")
    cov.set_defaults(func=cmd_coverage)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("quantlab").error("%s: %s", type(exc).__name__, exc)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

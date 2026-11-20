"""A run's replay, recorded once and played back as it happened.

Replaying a run used to mean simulating it again: its stored signals, but the
bars, corporate actions and minute data read *today*. Those change -- a vendor
revises a print, a split is restated, a symbol is re-ingested -- and when they
do, the "replay" shows fills, equity and a result the run never had. A replay
is a record of what a run did, so it is recorded when the run completes, from
exactly the inputs the run executed on, and afterwards only read.

The record is the event stream at ``step=1`` (every walked bar's frames),
gzip-compressed, one frame per line as ``kind<TAB>json`` -- the JSON exactly
the payload the SSE stream sends. A walked bar is a session for a daily run
and one intraday bar for an intraday run. A long intraday run is recorded at
granularity ``every``: only every Nth walked bar's bar and equity frames are
kept -- but every one with a signal or a fill is kept whole, so no trade is
ever missing its price or its mark. ``step`` then counts walked bars as
recorded. Writing it streams through the compressor, so even a long intraday run
holds only the compressed bytes in memory. Thinning (``step``) is applied on
the way out, with exactly the rule ``replay_events`` applies on the way in.

A run completed before recording existed has no record. It is reconstructed
once by re-execution against the data as it is now and stored with
``reconstructed=True`` -- the summary frame says so -- and never recomputed
again.
"""

from __future__ import annotations

import gzip
import io
import json
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from typing import Any

from quantlab.replay.engine import ReplayEvent, ReplaySummary, kind_of, to_dict


@dataclass(frozen=True)
class RecordedReplay:
    """A run's event stream as stored."""

    #: gzip, one ``kind<TAB>json`` frame per line (not NDJSON), ``step=1``.
    events: bytes
    #: The terminal summary frame's payload (without its ``event`` key).
    summary: dict[str, Any]
    #: True when re-executed after the fact rather than recorded at completion.
    reconstructed: bool = False


def strict_json(value: Any) -> Any:
    """Strict JSON: NaN and infinities become null.

    A NaN close makes equity NaN; Postgres JSONB refuses the ``NaN`` token,
    and so does a browser's JSON.parse on the SSE frame.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: strict_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict_json(v) for v in value]
    return value


Line = tuple[str, str]  # (event kind, the frame's JSON)


def _sessions(lines: Iterable[tuple[str, Any]]) -> Iterator[list[tuple[str, Any]]]:
    """Frames grouped by walked bar -- a session for a daily run, one bar of
    it for an intraday one: each group ends with its equity frame (or, last,
    the summary), so whether it carried a signal or a fill is known before
    any of its frames is let through."""
    held: list[tuple[str, Any]] = []
    for line in lines:
        held.append(line)
        if line[0] in ("equity", "summary"):
            yield held
            held = []
    if held:
        yield held


def _with_last(
    groups: Iterator[list[tuple[str, Any]]],
) -> Iterator[tuple[int, list[tuple[str, Any]], bool]]:
    """``(index, group, is_last_walked_bar)``: one group of lookahead, so the
    bar before the closing summary is known as the last."""
    held: list[tuple[str, Any]] | None = None
    index = 0
    for group in groups:
        if held is not None:
            closing = group[0][0] == "summary"
            yield index, held, closing
            index += 1
        held = group
    if held is not None:
        yield index, held, False


def _has(group: list[tuple[str, Any]], *kinds: str) -> bool:
    return any(kind in kinds for kind, _ in group)


def record(
    events: Iterable[ReplayEvent],
    *,
    reconstructed: bool = False,
    every: int = 1,
    bars_every: int = 1,
) -> RecordedReplay:
    """Compress a finished replay stream; the last event must be its summary.

    Each line is ``kind<TAB>json``: the kind lets playback group, thin and
    pace frames without decoding them, and the JSON is sent exactly as stored.

    ``every`` > 1 keeps only every Nth walked bar's frames (bar and equity),
    plus every one that carries a signal or a fill, whole. ``bars_every`` > 1
    further keeps only every Nth kept bar frame -- equity marks stay -- again
    never one whose date carries a signal or fill.
    """
    summary: dict[str, Any] | None = None

    def encode(event: ReplayEvent) -> str:
        nonlocal summary
        if isinstance(event, ReplaySummary):
            event = replace(event, reconstructed=reconstructed)
        frame = strict_json(to_dict(event))
        if frame["event"] == "summary":
            summary = {k: v for k, v in frame.items() if k != "event"}
        return json.dumps(frame, sort_keys=True, allow_nan=False)

    # Kept or dropped by kind alone, and only kept frames are encoded: a
    # thinned intraday record drops nearly all of its frames.
    kinds = ((kind_of(event), event) for event in events)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as out:
        for session, group, last in _with_last(_sessions(kinds)):
            # The final walked bar too, so a thinned curve ends where the run
            # did and its last mark is the summary's.
            eventful = last or _has(group, "signal", "fill")
            keep = every <= 1 or session % every == 0 or eventful
            keep_bar = bars_every <= 1 or (session // every) % bars_every == 0 or eventful
            for kind, event in group:
                if (not keep and kind != "summary") or (kind == "bar" and not keep_bar):
                    continue
                out.write(f"{kind}\t{encode(event)}\n".encode())
    if summary is None:
        raise ValueError("a replay stream must end with its summary")
    return RecordedReplay(events=buffer.getvalue(), summary=summary, reconstructed=reconstructed)


def _lines(events: bytes) -> Iterator[Line]:
    with gzip.GzipFile(fileobj=io.BytesIO(events), mode="rb") as source:
        for raw in source:
            text = raw.decode().rstrip("\n")
            if text:
                kind, _, payload = text.partition("\t")
                yield kind, payload


def frames(events: bytes) -> Iterator[dict[str, Any]]:
    """Every recorded frame, in order, decoded."""
    for _, payload in _lines(events):
        yield json.loads(payload)


def playback_lines(events: bytes, step: int = 1) -> Iterator[Line]:
    """The recorded stream as ``(kind, json)``, thinned to every ``step``-th
    walked bar's bar frame -- nothing decoded, so a stream is sent as stored.

    The same rule ``replay_events`` applies: a bar frame is kept when its
    count is a multiple of ``step``, and one whose bar carries a signal or a
    fill always is, so a fill never appears without its price. Signal, fill,
    equity and summary frames are never thinned.
    """
    if step <= 1:
        yield from _lines(events)
        return
    # Counted over the bar frames the record kept, not over its groups: a
    # thinned record (``bars_every``) holds groups whose bar frame it dropped,
    # and counting those would space the bars unevenly and send too few.
    count = 0
    for group in _sessions(_lines(events)):
        if not _has(group, "bar"):
            yield from group
            continue
        keep_bar = count % step == 0 or _has(group, "signal", "fill")
        count += 1
        for kind, payload in group:
            if kind != "bar" or keep_bar:
                yield kind, payload


def playback(events: bytes, step: int = 1) -> Iterator[dict[str, Any]]:
    """``playback_lines``, decoded."""
    for _, payload in playback_lines(events, step):
        yield json.loads(payload)


__all__ = ["RecordedReplay", "frames", "playback", "playback_lines", "record", "strict_json"]

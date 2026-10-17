"""Live data never reaches research.

Tiingo is the source of truth; IBKR's live bars are provisional and for
display. The guarantee is structural: exactly one module (storage.live) reads
the `live` ClickHouse database, and nothing a backtest runs imports it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import quantlab

PACKAGE = Path(quantlab.__file__).parent
LIVE_SQL = re.compile(r"\blive\.bars_|\bFROM\s+live\.", re.IGNORECASE)
READER = PACKAGE / "storage" / "live.py"


def test_only_storage_live_names_the_live_database():
    offenders = [
        path.relative_to(PACKAGE).as_posix()
        for path in PACKAGE.rglob("*.py")
        if path != READER and LIVE_SQL.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_nothing_a_backtest_runs_imports_the_live_store():
    research_side = ("research", "replay", "execution", "signals", "strategy", "indicators")
    offenders = []
    for area in research_side:
        for path in (PACKAGE / area).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                if any(n.startswith(("quantlab.storage.live", "quantlab.streaming.live_hub"))
                       for n in names):
                    offenders.append(path.relative_to(PACKAGE).as_posix())
    assert offenders == []

"""Every signal-rule parameter has a unit in the UI's glossary.

The hover explanation of a parameter is the rule's own description plus a unit
from frontend/src/glossary/params.ts. A parameter added to a rule without a
unit there would hover with no unit line; this says so, by name.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quantlab.signals import registry

PARAMS_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "glossary" / "params.ts"


def _keys(source: str, table: str) -> set[str]:
    body = re.search(rf"const {table}: Record<string, UnitKind> = \{{(.*?)\n\}};", source, re.S)
    assert body, f"{table} not found in params.ts"
    return set(re.findall(r"^\s*'?([\w.-]+)'?\s*:", body.group(1), re.M))


@pytest.mark.skipif(not PARAMS_TS.is_file(), reason="frontend not present (backend-only checkout)")
def test_every_registered_parameter_has_a_unit():
    source = PARAMS_TS.read_text()
    by_rule_param = _keys(source, "BY_RULE_PARAM")
    by_name = _keys(source, "BY_NAME")

    missing = sorted(
        f"{rule.name}.{name}"
        for rule in registry.list_rules()
        for name in rule.param_specs
        if f"{rule.name}.{name}" not in by_rule_param and name not in by_name
    )

    assert missing == [], f"add these to frontend/src/glossary/params.ts: {missing}"

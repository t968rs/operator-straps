"""agent-watcher keeps a generic core apart from its skill layers (issue #195).

``hooks/core/`` never imports from ``hooks/layers/``; ``hooks/register.ts`` is the one file that wires both,
registering the core with the layer list and each layer's own hooks by a direct call. The layer contract in
``hooks/core/layer.ts`` never hands a layer the engine (``$``) or ``on``: the engine refuses either passed
through an object, so a layer reaches the host only through the ``Io`` the core builds.
"""
from __future__ import annotations

import re

from conftest import REPO_ROOT

WALK_ROOTS = ("plugins/agent-watcher/",)

HOOKS = REPO_ROOT / "plugins" / "agent-watcher" / "hooks"
CORE = HOOKS / "core"
IMPORT_FROM = re.compile(r"""^\s*(?:import|export)\b[^'"]*from\s+['"]([^'"]+)['"]""", re.MULTILINE)


def _core_sources() -> list:
    files = sorted(p for p in CORE.glob("*.ts*") if p.is_file())
    assert files, f"no core sources under {CORE}"
    return files


def test_core_never_imports_a_layer() -> None:
    offenders = [f"{path.name}: {spec}" for path in _core_sources()
                 for spec in IMPORT_FROM.findall(path.read_text(encoding="utf-8")) if "layers" in spec]
    assert offenders == [], f"core imports a layer: {offenders}"


def test_register_wires_core_and_the_pr_review_layer() -> None:
    register = HOOKS / "register.ts"
    text = register.read_text(encoding="utf-8") if register.is_file() else ""
    assert re.search(r"registerCore\(on,\s*LAYERS\)", text), "register.ts does not register the core"
    assert "registerPrReviewLayer(on)" in text, "register.ts does not register the pr-review layer's hooks"


def test_the_layer_contract_never_takes_the_engine() -> None:
    contract = CORE / "layer.ts"
    assert contract.is_file(), f"{contract} is missing"
    text = contract.read_text(encoding="utf-8")
    assert re.search(r"export type Layer\b", text) and re.search(r"export type Io\b", text)
    assert not re.search(r"\$\s*[:?]", text), "the layer contract names `$`"
    assert "EngineInterface" not in text and not re.search(r"\bOn\b", text)

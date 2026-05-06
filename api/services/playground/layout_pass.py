"""Static safe-zone adjustments on manifest before codegen."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

SAFE_X = 6.5
SAFE_Y = 3.5


def apply_layout_pass(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-safe copy of manifest with layout hints attached."""
    m = deepcopy(manifest)
    mobjects = m.get("mobjects") or []
    needs_scale = False
    for mo in mobjects:
        pos = mo.get("position") or {}
        x = float(pos.get("x", 0))
        y = float(pos.get("y", 0))
        if abs(x) > SAFE_X or abs(y) > SAFE_Y:
            needs_scale = True
        p = mo.get("params") or {}
        mtype = mo.get("type")
        if mtype in ("Text", "MathTex"):
            fs = float(p.get("font_size", 24))
            content = str(p.get("text_content") or p.get("tex_string") or "")
            if fs > 36 or len(content) > 40:
                mo.setdefault("_layout", {})["scale_to_fit_width"] = 12.0
    m.setdefault("_layout_hints", {})["post_group_scale"] = needs_scale
    return m


def post_construct_scale_line() -> str:
    """Emitted at end of construct() when safe zone exceeded."""
    return "VGroup(*self.mobjects).scale_to_fit_width(12).move_to(ORIGIN)"

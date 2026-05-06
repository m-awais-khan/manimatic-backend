"""Deterministic manifest → Python Scene source (trusted server compile)."""
from __future__ import annotations

import re
from typing import Any, List, Tuple

from .layout_pass import post_construct_scale_line
from .snippets import SNIPPET_REGISTRY

PI = 3.141592653589793

DEFAULT_MOBJECT_PARAMS: dict[str, dict[str, Any]] = {
    "Circle": {"radius": 1.0, "color": "BLUE", "fill_opacity": 0.7, "stroke_width": 4},
    "Square": {"side_length": 2.0, "color": "BLUE", "fill_opacity": 0.7, "stroke_width": 4},
    "Polygon": {
        "vertices": "[(0, 0, 0), (2, 0, 0), (1, 1.5, 0)]",
        "color": "BLUE",
        "fill_opacity": 0.7,
        "stroke_width": 4,
    },
    "Annulus": {
        "inner_radius": 1.0,
        "outer_radius": 2.0,
        "color": "BLUE",
        "fill_opacity": 0.5,
        "stroke_width": 4,
    },
    "Text": {"text_content": "Hello", "font_size": 28, "color": "WHITE"},
    "MathTex": {"tex_string": r"E = mc^2", "font_size": 36, "color": "WHITE"},
    "Axes": {
        "x_range": "[-4, 4, 1]",
        "y_range": "[-3, 3, 1]",
        "x_length": 8,
        "y_length": 6,
        "axis_config": '{"include_tip": True}',
    },
    "NumberPlane": {
        "x_range": "[-4, 4, 1]",
        "y_range": "[-3, 3, 1]",
        "x_length": 8,
        "y_length": 6,
    },
    "VGroup": {"member_ids": [], "direction": "DOWN", "buff": 0.5},
}


def _sanitize_var_prefix(prefix: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]", "_", prefix)
    if s and s[0].isdigit():
        s = "_" + s
    return s or "obj"


class CompileContext:
    def __init__(self) -> None:
        self.var_table: dict[str, str] = {}
        self.alias: dict[str, str] = {}
        self.counts: dict[str, int] = {}
        self.body: list[str] = []

    def alloc_var(self, prefix: str) -> str:
        p = _sanitize_var_prefix(prefix)
        n = self.counts.get(p, 0) + 1
        self.counts[p] = n
        return f"{p}_{n}"

    def resolve_var(self, mobject_id: str) -> str:
        if mobject_id in self.alias:
            return self.alias[mobject_id]
        return self.var_table[mobject_id]


def _merge_params(mo_type: str, params: dict[str, Any]) -> dict[str, Any]:
    base = dict(DEFAULT_MOBJECT_PARAMS.get(mo_type, {}))
    base.update(params or {})
    return base


def _placement_line(var: str, mo: dict[str, Any]) -> str:
    al = mo.get("alignment")
    pos = mo.get("position") or {}
    x, y, z = float(pos.get("x", 0)), float(pos.get("y", 0)), float(pos.get("z", 0))
    if al:
        if str(al).strip().startswith("to_edge"):
            return f"{var}.{al}"
        return f"{var}.to_edge({al})"
    return f"{var}.move_to([{x}, {y}, {z}])"


def _emit_mobject(ctx: CompileContext, mo: dict[str, Any]) -> None:
    mid = mo["id"]
    mtype = mo["type"]
    params = _merge_params(mtype, mo.get("params") or {})

    if mtype == "VGroup":
        member_ids = params.get("member_ids") or []
        if not member_ids:
            raise ValueError("VGroup requires member_ids")
        members = ", ".join(ctx.resolve_var(str(x)) for x in member_ids)
        var = ctx.alloc_var("vgroup")
        ctx.var_table[mid] = var
        direction = params.get("direction", "DOWN")
        buff = float(params.get("buff", 0.5))
        ctx.body.append(f"{var} = VGroup({members}).arrange({direction}, buff={buff})")
        ctx.body.append(_placement_line(var, mo))
        return

    if mtype == "CodeBlock":
        code = str(params.get("verbatim_code") or "").strip()
        var = ctx.alloc_var("code_mob")
        ctx.var_table[mid] = var
        if code:
            for line in code.split("\n"):
                ctx.body.append(line)
        return

    spec = SNIPPET_REGISTRY.get(mtype)
    if not spec or "construct" not in spec:
        raise ValueError(f"Unknown or non-mobject type: {mtype}")

    var_prefix = spec.get("var_prefix", mtype.lower())
    var = ctx.alloc_var(var_prefix)
    ctx.var_table[mid] = var

    fmt_params = dict(params)
    fmt_params["var"] = var
    for line in spec["construct"]:
        ctx.body.append(line.format(**fmt_params))

    lay = mo.get("_layout") or {}
    if lay.get("scale_to_fit_width"):
        ctx.body.append(f"{var}.scale_to_fit_width({float(lay['scale_to_fit_width'])})")

    ctx.body.append(_placement_line(var, mo))


def _animation_expr(ctx: CompileContext, step: dict[str, Any]) -> str:
    atype = step.get("type")
    targets = list(step.get("targets") or [])
    rt = float(step.get("run_time", 1.0))
    spec = SNIPPET_REGISTRY.get(str(atype))
    if not spec or "play" not in spec:
        raise ValueError(f"Unknown animation: {atype}")

    if atype in ("Transform", "ReplacementTransform"):
        if len(targets) != 2:
            raise ValueError(f"{atype} requires exactly 2 targets")
        src_id, tgt_id = targets[0], targets[1]
        src_v = ctx.resolve_var(str(src_id))
        tgt_v = ctx.resolve_var(str(tgt_id))
        line = spec["play"].format(source=src_v, target=tgt_v, run_time=rt)
        if spec.get("merge_source_into_target"):
            ctx.alias[str(tgt_id)] = src_v
        return line

    if len(targets) < 1:
        raise ValueError(f"{atype} requires at least one target")
    tgt_v = ctx.resolve_var(str(targets[0]))
    angle = float(step.get("angle", PI))
    return spec["play"].format(target=tgt_v, run_time=rt, angle=angle)


def _timeline_step_lines(ctx: CompileContext, step: dict[str, Any]) -> list[str]:
    kind = step.get("kind")
    if kind == "wait":
        return [f"self.wait({float(step.get('duration', 1.0))})"]

    if kind == "parallel":
        children = step.get("children") or []
        exprs: list[str] = []
        for ch in children:
            ck = ch.get("kind")
            if ck == "animation":
                exprs.append(_animation_expr(ctx, ch))
            elif ck == "wait":
                raise ValueError("Nested wait inside parallel not supported in codegen")
            elif ck == "parallel":
                raise ValueError("Nested parallel not supported")
        if not exprs:
            return []
        return [f"self.play({', '.join(exprs)})"]

    if kind == "animation":
        expr = _animation_expr(ctx, step)
        return [f"self.play({expr})"]

    if kind == "sequential":
        out: list[str] = []
        for ch in step.get("children") or []:
            out.extend(_timeline_step_lines(ctx, ch))
        return out

    return []


def _compile_class_body(manifest: dict[str, Any]) -> Tuple[List[str], CompileContext]:
    ctx = CompileContext()
    for mo in manifest.get("mobjects") or []:
        _emit_mobject(ctx, mo)

    for step in manifest.get("timeline") or []:
        for line in _timeline_step_lines(ctx, step):
            ctx.body.append(line)

    hints = manifest.get("_layout_hints") or {}
    if hints.get("post_group_scale"):
        ctx.body.append(post_construct_scale_line())

    indented_lines = [f"        {b}" for b in ctx.body]
    return indented_lines, ctx


def compile_manifest_to_python(manifest: dict[str, Any]) -> str:
    """Full module: imports + main scene_class + optional sub_scenes as extra classes."""
    scene_class = manifest.get("scene_class") or "GeneratedScene"
    body_lines, _ = _compile_class_body(manifest)

    lines = [
        "# AUTO-GENERATED by Manimatic Visual Playground (deterministic compiler)",
        "from manim import *",
        "",
        f"class {scene_class}(Scene):",
        "    def construct(self):",
    ]
    if body_lines:
        lines.extend(body_lines)
    else:
        lines.append("        pass")

    out = "\n".join(lines)

    for ss in manifest.get("sub_scenes") or []:
        inner = ss.get("manifest") or {}
        sub_name = ss.get("scene_class") or "SubSceneGenerated"
        sub_lines, _ = _compile_class_body(inner)
        out += "\n\n"
        out += f"class {sub_name}(Scene):\n"
        out += "    def construct(self):\n"
        if sub_lines:
            out += "\n".join(sub_lines) + "\n"
        else:
            out += "        pass\n"

    return out + "\n"

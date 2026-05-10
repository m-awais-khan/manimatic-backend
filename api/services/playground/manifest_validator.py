"""Pydantic validation for Animation Manifest JSON from the Playground."""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .snippets import SNIPPET_REGISTRY


class FrameSpec(BaseModel):
    width: float = 14.22
    height: float = 8.0


class PositionSpec(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class MobjectSpec(BaseModel):
    id: str
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    position: PositionSpec = Field(default_factory=PositionSpec)
    alignment: Optional[str] = None


class ManifestMetadata(BaseModel):
    source: str = "playground"
    playground_version: str = "1.0"


class AnimationManifest(BaseModel):
    version: str = "1.0"
    scene_class: str = "GeneratedScene"
    frame: FrameSpec = Field(default_factory=FrameSpec)
    mobjects: List[MobjectSpec] = Field(default_factory=list)
    timeline: List[dict[str, Any]] = Field(default_factory=list)
    sub_scenes: List[dict[str, Any]] = Field(default_factory=list)
    metadata: ManifestMetadata = Field(default_factory=ManifestMetadata)

    @field_validator("mobjects")
    @classmethod
    def unique_mobject_ids(cls, v: List[MobjectSpec]) -> List[MobjectSpec]:
        ids = [m.id for m in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate mobject id in manifest")
        for mo in v:
            if mo.type not in SNIPPET_REGISTRY:
                raise ValueError(f"Unknown mobject type: {mo.type}")
        return v

    @model_validator(mode="after")
    def validate_timeline(self) -> "AnimationManifest":
        ids = {m.id for m in self.mobjects}
        allowed_kinds = {"animation", "wait", "parallel", "sequential"}

        def check_step(step: dict[str, Any], path: str) -> None:
            kind = step.get("kind")
            if kind not in allowed_kinds:
                raise ValueError(f"{path}: unknown timeline kind {kind!r}")
            if kind == "wait":
                duration = float(step.get("duration", 1.0))
                if duration < 0:
                    raise ValueError(f"{path}: wait duration must be non-negative")
                return
            if kind in {"parallel", "sequential"}:
                children = step.get("children") or []
                if not isinstance(children, list):
                    raise ValueError(f"{path}: children must be a list")
                for i, child in enumerate(children):
                    check_step(child, f"{path}.children[{i}]")
                return

            atype = step.get("type")
            # "None" is a valid sentinel meaning "no animation" — skip all further checks
            if atype == "None":
                return
            spec = SNIPPET_REGISTRY.get(str(atype))
            if not spec or "play" not in spec:
                raise ValueError(f"{path}: unknown animation type {atype!r}")
            required = int(spec.get("target_count", 1))
            targets = list(step.get("targets") or [])
            if required > 0:
                if len(targets) < required:
                    raise ValueError(f"{path}: {atype} requires {required} target(s)")
                missing = [t for t in targets if t not in ids]
                if missing:
                    raise ValueError(f"{path}: target id(s) not found: {', '.join(missing)}")
                if float(step.get("run_time", 1.0)) <= 0:
                    raise ValueError(f"{path}: run_time must be positive")


        for i, step in enumerate(self.timeline):
            check_step(step, f"timeline[{i}]")
        return self


def validate_manifest(data: dict) -> AnimationManifest:
    return AnimationManifest.model_validate(data)

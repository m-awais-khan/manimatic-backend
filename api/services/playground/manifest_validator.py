"""Pydantic validation for Animation Manifest JSON from the Playground."""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


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
        return v


def validate_manifest(data: dict) -> AnimationManifest:
    return AnimationManifest.model_validate(data)

"""Snippet templates keyed by manifest node type (Mobject / Animation / Logic)."""
from .geometry import GEOMETRY
from .text import TEXT
from .coordinate import COORDINATE
from .animations import ANIMATIONS
from .logic import LOGIC

SNIPPET_REGISTRY = {}
for d in (GEOMETRY, TEXT, COORDINATE, ANIMATIONS, LOGIC):
    SNIPPET_REGISTRY.update(d)

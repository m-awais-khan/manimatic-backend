"""Animation snippets — play_* templates."""

ANIMATIONS = {
    "FadeIn": {
        "play": "FadeIn({target}, run_time={run_time})",
        "target_count": 1,
    },
    "FadeOut": {
        "play": "FadeOut({target}, run_time={run_time})",
        "target_count": 1,
    },
    "Write": {
        "play": "Write({target}, run_time={run_time})",
        "target_count": 1,
    },
    "Create": {
        "play": "Create({target}, run_time={run_time})",
        "target_count": 1,
    },
    "Uncreate": {
        "play": "Uncreate({target}, run_time={run_time})",
        "target_count": 1,
    },
    "DrawBorderThenFill": {
        "play": "DrawBorderThenFill({target}, run_time={run_time})",
        "target_count": 1,
    },
    "GrowFromCenter": {
        "play": "GrowFromCenter({target}, run_time={run_time})",
        "target_count": 1,
    },
    "ShrinkToCenter": {
        "play": "ShrinkToCenter({target}, run_time={run_time})",
        "target_count": 1,
    },
    "SpinInFromNothing": {
        "play": "SpinInFromNothing({target}, run_time={run_time})",
        "target_count": 1,
    },
    "ShowCreationThenFadeOut": {
        "play": "ShowCreationThenFadeOut({target}, run_time={run_time})",
        "target_count": 1,
    },
    "Indicate": {
        "play": "Indicate({target}, run_time={run_time})",
        "target_count": 1,
    },
    "CircleIndicate": {
        "play": "CircleIndicate({target}, run_time={run_time})",
        "target_count": 1,
    },
    "Circumscribe": {
        "play": "Circumscribe({target}, run_time={run_time})",
        "target_count": 1,
    },
    "Flash": {
        "play": "Flash({target}, run_time={run_time})",
        "target_count": 1,
    },
    "Wiggle": {
        "play": "Wiggle({target}, run_time={run_time})",
        "target_count": 1,
    },
    "Rotate": {
        "play": "Rotate({target}, angle={angle}, run_time={run_time})",
        "target_count": 1,
    },
    "ScaleInPlace": {
        "play": "ScaleInPlace({target}, scale_factor=1.5, run_time={run_time})",
        "target_count": 1,
    },
    "Transform": {
        "play": "Transform({source}, {target}, run_time={run_time})",
        "target_count": 2,
        "merge_source_into_target": True,
    },
    "ReplacementTransform": {
        "play": "ReplacementTransform({source}, {target}, run_time={run_time})",
        "target_count": 2,
        "merge_source_into_target": True,
    },
    "None": {
        "play": "",  # skipped by compiler
        "target_count": 0,
    },
}

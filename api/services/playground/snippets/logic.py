"""Logic nodes — Wait, VGroup, Parallel handled in compiler; registry for metadata."""

LOGIC = {
    "Wait": {"kind": "wait"},
    "VGroup": {"kind": "vgroup", "var_prefix": "vgroup"},
    "Parallel": {"kind": "parallel"},
    "Sequential": {"kind": "sequential"},
    "SubScene": {"kind": "subscene"},
    "CodeBlock": {"kind": "codeblock"},
}

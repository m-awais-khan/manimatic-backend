"""Text Mobject snippets."""

TEXT = {
    "Text": {
        "var_prefix": "text",
        "params": ("text_content", "font_size", "color"),
        "construct": (
            "{var} = Text({text_content!r}, font_size={font_size}, color={color})",
        ),
    },
    "MathTex": {
        "var_prefix": "mathtex",
        "params": ("tex_string", "font_size", "color"),
        "construct": (
            "{var} = MathTex({tex_string!r}, font_size={font_size}, color={color})",
        ),
    },
}

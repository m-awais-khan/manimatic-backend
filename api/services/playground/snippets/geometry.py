"""Geometry Mobject snippet metadata — consumed by python_compiler."""

GEOMETRY = {
    "Circle": {
        "var_prefix": "circle",
        "params": ("radius", "color", "fill_opacity", "stroke_width"),
        "construct": (
            "{var} = Circle(radius={radius}, color={color}, fill_opacity={fill_opacity}, stroke_width={stroke_width})",
        ),
    },
    "Square": {
        "var_prefix": "square",
        "params": ("side_length", "color", "fill_opacity", "stroke_width"),
        "construct": (
            "{var} = Square(side_length={side_length}, color={color}, fill_opacity={fill_opacity}, stroke_width={stroke_width})",
        ),
    },
    "Polygon": {
        "var_prefix": "polygon",
        "params": ("vertices", "color", "fill_opacity", "stroke_width"),
        "construct": (
            "{var} = Polygon(*{vertices}, color={color}, fill_opacity={fill_opacity}, stroke_width={stroke_width})",
        ),
    },
    "Annulus": {
        "var_prefix": "annulus",
        "params": ("inner_radius", "outer_radius", "color", "fill_opacity", "stroke_width"),
        "construct": (
            "{var} = Annulus(inner_radius={inner_radius}, outer_radius={outer_radius}, color={color}, fill_opacity={fill_opacity}, stroke_width={stroke_width})",
        ),
    },
}

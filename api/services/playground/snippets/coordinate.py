"""Axes / NumberPlane snippets."""

COORDINATE = {
    "Axes": {
        "var_prefix": "axes",
        "params": ("x_range", "y_range", "x_length", "y_length", "axis_config"),
        "construct": (
            "{var} = Axes(x_range={x_range}, y_range={y_range}, x_length={x_length}, y_length={y_length}, axis_config={axis_config})",
        ),
    },
    "NumberPlane": {
        "var_prefix": "plane",
        "params": ("x_range", "y_range", "x_length", "y_length"),
        "construct": (
            "{var} = NumberPlane(x_range={x_range}, y_range={y_range}, x_length={x_length}, y_length={y_length})",
        ),
    },
}

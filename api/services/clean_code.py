import re
import logging
from api.services.utils import get_fallback_code

logger = logging.getLogger(__name__)


def sanitize_latex_escapes(code: str) -> str:
    """
    Two-step fix for LaTeX backslash corruption that can occur when an LLM
    response is JSON-decoded or passed through string processing.

    STEP 1 — Fix control-char corruptions introduced by JSON parsing:
      \f (form feed) + "rac"  →  single backslash + "frac"
      \t (tab)       + "ext"  →  single backslash + "text"  etc.

    STEP 2 — Double every single backslash before a known LaTeX command
      so the saved .py file contains \\frac and Python reads it as \frac
      at runtime (which is what MathTex / Manim expects).
    """
    # STEP 1: restore control-char corruptions to single-backslash
    F, T, N, B, R = chr(12), chr(9), chr(10), chr(8), chr(13)
    ctrl_fixes = [
        (F + "rac",  "\\frac"),
        (T + "ext",  "\\text"),
        (T + "heta", "\\theta"),
        (T + "an",   "\\tan"),
        (T + "imes", "\\times"),
        (N + "abla", "\\nabla"),
        (N + "eq",   "\\neq"),
        (B + "eta",  "\\beta"),
        (B + "ar",   "\\bar"),
        (R + "ight", "\\right"),
    ]
    for broken, correct in ctrl_fixes:
        code = code.replace(broken, correct)

    # STEP 2: find every single backslash before a known LaTeX command
    # and double it so the .py file has \\cmd → Python runtime gets \cmd
    latex_cmds = (
        "frac", "text", "theta", "tan", "times", "nabla", "neq",
        "beta", "bar", "right", "left", "sum", "sin", "cos", "sqrt",
        "pi", "alpha", "gamma", "delta", "int", "lim", "cdot",
        "leq", "geq", "partial", "vec", "hat", "bar", "lambda",
        "phi", "psi", "sigma", "mu", "omega", "infty", "pm",
    )
    # Match a single backslash NOT preceded by another backslash
    for cmd in latex_cmds:
        code = re.sub(r'(?<!\\)\\' + cmd, r'\\\\' + cmd, code)

    # STEP 3: Revert over-escaped commands inside raw strings (r"..." or r'...')
    # The LLM often correctly generates r"\frac" which step 2 corrupts to r"\\frac".
    def fix_raw_strings(match):
        inner = match.group(0)
        for cmd in latex_cmds:
            inner = inner.replace('\\\\' + cmd, '\\' + cmd)
        return inner

    code = re.sub(r'[rR](["\']).*?\1', fix_raw_strings, code, flags=re.DOTALL)

    return code


def clean_code(code):
    # Clean up the code - remove markdown code blocks if present
    code = code.strip()
    if code.startswith('```python'):
        code = code[len('```python'):]
    if code.startswith('```'):
        code = code[len('```'):]
    if code.endswith('```'):
        code = code[:-len('```')]

    # Remove any leading/trailing whitespace
    code = code.strip()

    # Ensure it starts with import or from statement
    if not (code.startswith('import') or code.startswith('from')):
        code = 'from manim import *\n\n' + code

    # Validate that it contains necessary components
    if 'class' not in code or "def construct(self):" not in code:
        logger.warning("LLM response incomplete, using fallback code...")
        return get_fallback_code()

    # Fix any LaTeX backslash corruption introduced during LLM generation
    # or JSON parsing before the code is written to disk for Manim rendering.
    code = sanitize_latex_escapes(code)

    return code

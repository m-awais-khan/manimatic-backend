from api.services.utils import get_fallback_code
import logging

logger = logging.getLogger(__name__)

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
    
    return code

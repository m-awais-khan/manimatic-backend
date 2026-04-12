def get_fallback_code():
    """Generate a fallback Manim code"""
    return '''from manim import *
class FallbackScene(Scene):
    def construct(self):
        text = Text("Sorry, something went wrong!")
        self.play(Write(text))
        self.wait(1)
'''

def code_validator(code):
    """Validate Python code for syntax errors"""
    try:
        compile(source=code, filename='<string>', mode='exec')
        return True, None
    except SyntaxError as e:
        return False, f"Syntax Error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Validation Error: {str(e)}"
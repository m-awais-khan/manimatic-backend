from backend.api import llm_client
from config import MODEL_NAME
import streamlit as st
from backend.utils import get_fallback_code

# Initialize the OpenAI client
client = llm_client.get_openai_client()

def get_llm_response(prompt, subject, animation_type, duration, background_color, text_color):
    """
    Get a response from the LLM based on the provided prompt.
    
    Args:
        prompt (str): The input prompt for the LLM.
    Returns:
        str: The response from the LLM.
    """

    # System prompt based on parameters
    system_prompt = f"""You are a highly trained Manim coder. Your sole responsibility is to generate Python code strictly for the Manim library. 

Requirements:
- Generate complete, runnable Manim code
- Animation duration: approximately {duration} seconds
- Text color: {text_color}
- Background color: {background_color}
- Subject area: {subject}
- Animation type: {animation_type}
- Include proper imports and scene class
- Use Scene class and construct method (not create_animation)
- Code should be production-ready and error-free
- Return ONLY Python code, no markdown formatting, no explanations
- Do not wrap code in ```python or ``` blocks
- Start directly with import statements

Example structure:
from manim import *

class MyScene(Scene):
    def construct(self):
        # Your animation code here
"""
    
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
        )

        response = completion.choices[0].message.content
        return response
    
    except Exception as e:
        st.error(f"Error getting LLM response: {str(e)}")
        st.info("Using fallback code...")
        response = get_fallback_code()
        return response
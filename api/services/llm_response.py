import os
import io
import base64
import logging
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# Load environment variables from .env
load_dotenv()

logger = logging.getLogger(__name__)

def get_llm_response(prompt, history=None, image_path=None, target_model='gemini-2.5-flash'):
    """
    Get a response from the LLM based on the provided prompt, history, and optional reference image.
    """

    system_prompt = f"""You are a highly trained Manim coder. Your primary responsibility is to generate Python code strictly for the Manim library. 

CRITICAL INSTRUCTION FOR CONVERSATION:
If the user asks a conversational question, greets you, or asks something NOT related to generating a Manim animation (e.g., 'How are you?', 'What is 2+2?', 'Who are you?'), YOU MUST reply in plain text AND prefix your entire response with the exact tag `[TEXT]`.
Example: `[TEXT] Hello! I am doing well. How can I help you animate today?`

Requirements for Animation:
- Generate complete, runnable Manim code
- You must decide and configure the animation duration, text colors, background colors, and styling based strictly on the user's prompt. Try to make it mathematically or visually appealing.
- Include proper imports and scene class
- Use Scene class and construct method (not create_animation)
- Code should be production-ready and error-free
- Return ONLY Python code, no markdown formatting, no explanations
- Do not wrap code in ```python or ``` blocks
- Start directly with import statements

CRITICAL FRAME RULES (YOU MUST ALWAYS FOLLOW THESE):
The Manim frame is 14.22 units wide and 8 units tall. The center is at (0, 0).
- The visible X range is approximately -7 to +7
- The visible Y range is approximately -4 to +4
- SAFE ZONE: Keep ALL objects within X: -6.5 to +6.5 and Y: -3.5 to +3.5 to avoid clipping

Text and Font Rules:
- NEVER use font_size larger than 48 for titles or 36 for body text
- For long text, ALWAYS use .scale_to_fit_width(12) or similar to ensure it fits
- For titles, use font_size=40 and .scale_to_fit_width(12) as a safety measure
- For subtitles, use font_size=28
- For labels, use font_size=24

Layout Rules:
- When placing multiple objects, use VGroup(...).arrange(DOWN, buff=0.5) to stack them neatly
- When placing objects side by side, use VGroup(...).arrange(RIGHT, buff=0.5)
- ALWAYS call .move_to(ORIGIN) or .center() on your main VGroup to ensure centering
- For complex scenes, use .scale(0.8) on the entire group as a safety margin
- Never hardcode positions beyond the safe zone boundaries

Shape and Object Rules:
- Keep shapes like squares, circles, triangles sized between 1-3 units unless specifically needed larger
- When building geometric constructions, scale the entire group to fit: group.scale_to_fit_height(6)
- For number lines and axes, set x_range and y_range within the safe zone
- Always use include_numbers=True sparingly and with font_size=20

Example structure:
from manim import *

class MyScene(Scene):
    def construct(self):
        # Your animation code here
"""
    
    if history is None:
        history = []

    if target_model == 'custom-manim-model':
        from langchain_openai import ChatOpenAI
        custom_url = os.getenv("CUSTOM_MODEL_URL", "http://localhost:8000/v1")
        custom_api_key = os.getenv("CUSTOM_MODEL_API_KEY", "dummy-api-key")
        try:
            llm = ChatOpenAI(
                model="custom-manim-model",
                temperature=0.1,
                api_key=custom_api_key,
                base_url=custom_url,
                max_tokens=2048
            )
        except Exception as e:
            logger.error(f"Failed to initialize custom model, falling back to Gemini. Error: {e}")
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.1,
                api_key=os.getenv("GEMINI_API_KEY")
            )
    elif target_model.startswith('groq-'):
        from langchain_openai import ChatOpenAI
        model_name = target_model.replace('groq-', '')
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            logger.error("GROQ_API_KEY not found. Falling back to Gemini.")
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.1,
                api_key=os.getenv("GEMINI_API_KEY")
            )
        else:
            try:
                llm = ChatOpenAI(
                    model=model_name,
                    temperature=0.1,
                    api_key=groq_api_key,
                    base_url="https://api.groq.com/openai/v1",
                    max_tokens=2048
                )
            except Exception as e:
                logger.error(f"Failed to initialize Groq model, falling back to Gemini. Error: {e}")
                llm = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    temperature=0.1,
                    api_key=os.getenv("GEMINI_API_KEY")
                )
    else:
        # Initialize the LangChain Gemini model
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1,
            api_key=os.getenv("GEMINI_API_KEY")
        )

    # Construct the message array
    messages = [SystemMessage(content=system_prompt)]
    
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
            
    # Add the current prompt (Handles multimodal if image exists)
    if image_path and os.path.exists(image_path):
        import mimetypes
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type:
            mime_type = "image/jpeg"
            
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            
        # Format the multimodal block as expected by LangChain
        image_data = f"data:{mime_type};base64,{encoded_string}"
        
        message_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data}}
        ]
        messages.append(HumanMessage(content=message_content))
    else:
        messages.append(HumanMessage(content=prompt))

    response = llm.invoke(messages)

    return response.content

import os
import io
import base64
import logging
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

class ManimResponse(BaseModel):
    is_animation: bool = Field(description="True if the user wants to generate or fix an animation, False for general chat or questions.")
    chat_response: Optional[str] = Field(description="Only used if is_animation is False. A conversational response steering the user back to animation.")
    code: Optional[str] = Field(description="The full runnable Manim Python code. Only used if is_animation is True.")

# Load environment variables from .env
load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are 'Manimatic', a specialized AI assistant that ONLY generates Manim (Python) animations.

YOUR PERSONALITY & SCOPE:
1. You only care about math, physics, data visualization, and animation.
2. If a user asks a general question (e.g., 'How are you?', 'Who won the game?'), you must politely decline and ask how you can help them with an animation.
   Example: "I am focused on creating animations! How can I help you visualize something today?"
3. If the user wants an animation, you generate high-quality, production-ready Manim code. 
4. CRITICAL: Do NOT provide any text, explanations, or comments outside of the 'code' field for animations. The 'chat_response' field should remain empty when 'is_animation' is True.

TECHNICAL RULES FOR MANIM:
- The Manim frame is 14.22 units wide and 8 units tall. The center is at (0, 0).
- SAFE ZONE: Keep ALL objects within X: -6.5 to +6.5 and Y: -3.5 to +3.5 to avoid clipping.
- Use Scene class and construct method.
- Return ONLY valid Python code in the 'code' field. No markdown formatting, no backticks.
- Text and Font Rules: NEVER use font_size larger than 48. For long text, ALWAYS use .scale_to_fit_width(12).
- Layout Rules: AVOID OVERLAPPING. Use VGroup(...).arrange(DOWN, buff=0.5) to stack objects.

RESPONSE FORMAT:
You must always respond by filling the provided structured schema (is_animation, chat_response, code).
"""

def get_llm_response(prompt, history=None, image_path=None, target_model='gemini-2.5-flash'):
    """
    Get a structured response from the LLM.
    """
    
    if history is None:
        history = []

    # Initialize the base LLM
    if target_model == 'custom-manim-model':
        from langchain_openai import ChatOpenAI
        custom_url = os.getenv("CUSTOM_MODEL_URL", "http://localhost:8000/v1")
        custom_api_key = os.getenv("CUSTOM_MODEL_API_KEY", "dummy-api-key")
        llm = ChatOpenAI(
            model="custom-manim-model",
            temperature=0.1,
            api_key=custom_api_key,
            base_url=custom_url,
            max_tokens=2048
        )
        # The error message explicitly asked for 'json_schema'
        try:
            structured_llm = llm.with_structured_output(ManimResponse, method="json_schema")
        except:
            structured_llm = llm.with_structured_output(ManimResponse, method="function_calling")
    elif target_model.startswith('groq-'):
        from langchain_openai import ChatOpenAI
        model_name = target_model.replace('groq-', '')
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)
            structured_llm = llm.with_structured_output(ManimResponse)
        else:
            llm = ChatOpenAI(
                model=model_name,
                temperature=0.1,
                api_key=groq_api_key,
                base_url="https://api.groq.com/openai/v1",
                max_tokens=2048
            )
            try:
                structured_llm = llm.with_structured_output(ManimResponse, method="function_calling")
            except:
                structured_llm = llm.with_structured_output(ManimResponse, method="json_mode")
    else:
        # Default to Gemini 2.5 Flash for structured output support in 2026
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1,
            google_api_key=os.getenv("GEMINI_API_KEY")
        )
        structured_llm = llm.with_structured_output(ManimResponse)

    # Construct the message array
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            # For history, we just pass the content. 
            messages.append(AIMessage(content=msg["content"]))
            
    # Add current prompt
    if image_path and os.path.exists(image_path):
        import mimetypes
        mime_type, _ = mimetypes.guess_type(image_path)
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        
        image_data = f"data:{mime_type or 'image/jpeg'};base64,{encoded_string}"
        message_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data}}
        ]
        messages.append(HumanMessage(content=message_content))
    else:
        messages.append(HumanMessage(content=prompt))

    try:
        response = structured_llm.invoke(messages)
        return response
    except Exception as e:
        import traceback
        error_info = traceback.format_exc()
        with open("llm_error.log", "a") as f:
            f.write(f"\n--- ERROR ---\n{error_info}\n")
        logger.error(f"Error getting structured response: {e}")
        # Fallback to a user-friendly message
        return ManimResponse(
            is_animation=False,
            chat_response="I'm having trouble connecting to my animation engine right now. Please try again in a moment.",
            code=None
        )

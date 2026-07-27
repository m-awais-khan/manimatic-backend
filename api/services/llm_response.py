import os
import io
import base64
import logging
import requests
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
- SAFE ZONE: Keep all visible objects within the safe zone X(-6.5, 6.5), Y(-3.5, 3.5). For large VGroups, call scale_to_fit_width(12) or scale_to_fit_height(6.5), then center with move_to(ORIGIN). Do not place labels directly on the frame edge.
- Use Scene class and construct method.
- Return ONLY valid Python code in the 'code' field. No markdown formatting, no backticks.
- Text and Font Rules: NEVER use font_size larger than 48. For long text, ALWAYS use .scale_to_fit_width(12).
- Layout Rules: AVOID OVERLAPPING. Use VGroup(...).arrange(DOWN, buff=0.5) to stack objects. When adding text to shapes (like array boxes), explicitly position the text (e.g., text.move_to(box.get_center())) so they don't overlap at the origin.

RESPONSE FORMAT:
You must always respond by filling the provided structured schema (is_animation, chat_response, code).
"""

MODAL_32B_MODEL_ID = "manimatic-qwen32b-modal"


def _get_modal_32b_response(prompt, history=None):
    modal_url = (os.getenv("MODAL_MANIMATIC_32B_URL") or "").rstrip("/")
    if not modal_url:
        raise RuntimeError("MODAL_MANIMATIC_32B_URL is not configured.")

    timeout_seconds = int(os.getenv("MODAL_MANIMATIC_32B_TIMEOUT_SECONDS", "900"))
    api_key = os.getenv("MODAL_MANIMATIC_32B_API_KEY")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # The Modal endpoint owns the fine-tuned prompt/schema contract. We keep the
    # backend request small so cold-start and inference time are the only delays.
    payload = {
        "prompt": prompt,
        "complexity": os.getenv("MODAL_MANIMATIC_32B_DEFAULT_COMPLEXITY", "Medium"),
        "category": os.getenv("MODAL_MANIMATIC_32B_DEFAULT_CATEGORY", "General Manim"),
        "max_new_tokens": int(os.getenv("MODAL_MANIMATIC_32B_MAX_NEW_TOKENS", "1800")),
        "temperature": float(os.getenv("MODAL_MANIMATIC_32B_TEMPERATURE", "0.1")),
    }

    response = requests.post(
        f"{modal_url}/generate",
        json=payload,
        headers=headers,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()

    return ManimResponse(
        is_animation=bool(data.get("is_animation", False)),
        chat_response=data.get("chat_response") or None,
        code=data.get("code") or None,
    )


def get_llm_response(prompt, history=None, image_path=None, target_model='gemini-2.5-flash'):
    """
    Get a structured response from the LLM.
    """
    
    if history is None:
        history = []

    if target_model == MODAL_32B_MODEL_ID:
        try:
            return _get_modal_32b_response(prompt=prompt, history=history)
        except requests.Timeout:
            logger.exception("Modal 32B model timed out.")
            return ManimResponse(
                is_animation=False,
                chat_response=(
                    "The 32B Manimatic model is still waking up on Modal. "
                    "Please try again in a moment."
                ),
                code=None,
            )
        except Exception as e:
            logger.exception("Modal 32B model request failed: %s", e)
            return ManimResponse(
                is_animation=False,
                chat_response=(
                    "The 32B Manimatic model is temporarily unavailable. "
                    "Please try again or switch to Gemini."
                ),
                code=None,
            )

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
        # Default to Gemini 2.5 Flash
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
        return ManimResponse(
            is_animation=False,
            chat_response="I'm having trouble connecting to my animation engine right now. Please try again in a moment.",
            code=None
        )

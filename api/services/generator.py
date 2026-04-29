from api.models import Scene
from api.services.llm_response import get_llm_response
from api.services.manim_processor import execute_manim_code
from api.services.clean_code import clean_code
import logging
import re

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def _extract_error_summary(error_msg):
    """
    Extract a clean, concise error from verbose Manim output.
    The LLM only needs the actual Python error, not progress bars.
    """
    lines = error_msg.strip().split('\n')
    
    # Look for the actual error line (e.g., NameError, TypeError, ValueError, etc.)
    error_patterns = [
        r'(NameError: .+)',
        r'(TypeError: .+)',
        r'(ValueError: .+)',
        r'(AttributeError: .+)',
        r'(IndexError: .+)',
        r'(KeyError: .+)',
        r'(ImportError: .+)',
        r'(ModuleNotFoundError: .+)',
        r'(SyntaxError: .+)',
        r'(ZeroDivisionError: .+)',
        r'(RuntimeError: .+)',
        r'(Exception: .+)',
    ]
    
    for line in reversed(lines):
        line = line.strip()
        for pattern in error_patterns:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
    
    # Fallback: return last non-empty line (often the error itself)
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('|') and 'Animation' not in stripped and '%' not in stripped:
            return stripped[:300]
    
    return error_msg[:300]


def generate_scene_task(scene_id, quality='720p'):
    """
    Background task to generate code from LLM and then execute Manim.
    Implements a self-healing agent loop: if Manim execution fails,
    the error is fed back to the LLM to fix the code, up to MAX_RETRIES times.
    """
    try:
        scene = Scene.objects.get(id=scene_id)
    except Scene.DoesNotExist:
        logger.error(f"Scene {scene_id} not found.")
        return

    try:
        # 1. Fetch Chat History (Sliding Window)
        history = []
        if scene.chat:
            # Fetch last 5 scenes max to prevent context overflow (especially for local models)
            recent_scenes = list(Scene.objects.filter(
                chat=scene.chat, 
                created_at__lt=scene.created_at
            ).order_by('-created_at')[:5])
            
            # Reverse to restore chronological order
            recent_scenes.reverse()

            for past_scene in recent_scenes:
                if past_scene.code and past_scene.status == 'completed':
                    history.append({
                        "role": "user",
                        "content": past_scene.prompt
                    })
                    history.append({
                        "role": "model",
                        "content": past_scene.code
                    })

        # 2. Generate code from LLM
        scene.status = 'generating_code'
        scene.save()
        
        image_path = scene.reference_image.path if scene.reference_image else None
        
        raw_output = get_llm_response(prompt=scene.prompt, history=history, image_path=image_path, target_model=scene.target_model)
        
        # Check if conversational text response
        if raw_output.strip().startswith("[TEXT]"):
            text_reply = raw_output.replace("[TEXT]", "").strip()
            scene.text_response = text_reply
            scene.status = 'completed'
            scene.save()
            return

        code = clean_code(raw_output)
        scene.code = code
        scene.status = 'rendering'
        scene.save()

        # 3. Agent Loop — Execute and self-heal on errors
        current_code = code
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"Scene {scene_id}: Execution attempt {attempt}/{MAX_RETRIES}")
            
            video_url, error = execute_manim_code(current_code, str(scene_id), quality=quality)

            if not error:
                # Success!
                scene.status = 'completed'
                scene.video_path = video_url
                scene.code = current_code
                scene.save()
                logger.info(f"Scene {scene_id}: Completed on attempt {attempt}")
                return

            # Execution failed — extract clean error
            last_error = error
            clean_error = _extract_error_summary(error)
            logger.warning(f"Scene {scene_id}: Attempt {attempt} failed — {clean_error}")

            if attempt < MAX_RETRIES:
                # Feed error back to LLM for self-correction
                scene.status = 'generating_code'
                scene.save()

                fix_prompt = (
                    f"The code you generated has an error when executed by Manim.\n\n"
                    f"ERROR: {clean_error}\n\n"
                    f"Here is the failing code:\n```python\n{current_code}\n```\n\n"
                    f"Fix this error and return the complete corrected code. "
                    f"Return ONLY the fixed Python code, no explanations."
                )

                # Build history with the failed attempt
                retry_history = history.copy()
                retry_history.append({"role": "user", "content": scene.prompt})
                retry_history.append({"role": "model", "content": current_code})

                raw_fix = get_llm_response(prompt=fix_prompt, history=retry_history, target_model=scene.target_model)
                
                # Check if LLM returned text instead of code
                if raw_fix.strip().startswith("[TEXT]"):
                    logger.warning(f"Scene {scene_id}: LLM returned text on retry, breaking loop")
                    break
                
                fixed_code = clean_code(raw_fix)
                current_code = fixed_code
                scene.code = fixed_code
                scene.status = 'rendering'
                scene.save()

        # All retries exhausted
        scene.status = 'error'
        scene.error_message = (
            "The AI was unable to generate a working animation after multiple attempts. "
            "Please try simplifying your prompt or describing the animation differently."
        )
        scene.save()
        logger.error(f"Scene {scene_id}: All {MAX_RETRIES} attempts failed. Last error: {_extract_error_summary(last_error)}")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Task error for scene {scene_id}: {error_msg}")
        
        if "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
            error_msg = "Google Gemini API Token Limit Exceeded. Please wait a short while for the quota to reset and try again."
        else:
            error_msg = (
                "An unexpected error occurred while generating your animation. "
                "Please try again with a different prompt."
            )
        
        scene.status = 'error'
        scene.error_message = error_msg
        scene.save()

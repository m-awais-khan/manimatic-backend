from api.models import Scene
from api.services.llm_response import get_llm_response
from api.services.manim_processor import execute_manim_code
from api.services.clean_code import clean_code
import logging
import re
import threading

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def _extract_error_summary(error_msg):
    """
    Extract a clean, concise error from verbose Manim output.
    """
    if not error_msg:
        return "Unknown error"
        
    lines = error_msg.strip().split('\n')
    
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
    
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('|') and 'Animation' not in stripped and '%' not in stripped:
            return stripped[:300]
    
    return error_msg[:300]


def generate_scene_task(scene_id, quality='720p'):
    """
    Background task to generate code from LLM and then execute Manim.
    Implements a self-healing agent loop.
    """
    try:
        scene = Scene.objects.get(id=scene_id)
    except Scene.DoesNotExist:
        logger.error(f"Scene {scene_id} not found.")
        return

    try:
        # 1. Fetch Chat History
        history = []
        if scene.chat:
            recent_scenes = list(Scene.objects.filter(
                chat=scene.chat, 
                created_at__lt=scene.created_at
            ).order_by('-created_at')[:5])
            
            recent_scenes.reverse()

            for past_scene in recent_scenes:
                if past_scene.code and past_scene.status == 'completed':
                    history.append({"role": "user", "content": past_scene.prompt})
                    history.append({"role": "model", "content": past_scene.code})

        # 2. Generate code from LLM
        scene.status = 'generating_code'
        scene.save()
        
        image_path = scene.reference_image.path if scene.reference_image else None
        
        structured_res = get_llm_response(prompt=scene.prompt, history=history, image_path=image_path, target_model=scene.target_model)
        
        if not structured_res.is_animation or not structured_res.code:
            scene.text_response = structured_res.chat_response
            scene.status = 'completed'
            scene.save()
            return

        scene.text_response = None
        code = clean_code(structured_res.code)
        scene.code = code
        scene.status = 'rendering'
        
        # Initialize manifest with history tracking
        scene.manifest = {
            "attempt": 1,
            "history": [],
            "repairing": False
        }
        scene.save()

        # 3. Agent Loop — Execute and self-heal on errors
        current_code = code
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"Scene {scene_id}: Execution attempt {attempt}/{MAX_RETRIES}")
            
            # Update current attempt in manifest
            manifest = scene.manifest or {"history": []}
            manifest["attempt"] = attempt
            manifest["repairing"] = (attempt > 1)
            scene.manifest = manifest
            scene.save()
            
            video_url, error = execute_manim_code(current_code, str(scene_id), quality=quality)

            if not error:
                scene.status = 'completed'
                scene.video_path = video_url
                scene.code = current_code
                scene.error_message = None
                scene.save()
                return

            last_error = error
            clean_error = _extract_error_summary(error)
            
            # Record the failure in manifest history
            manifest = scene.manifest or {"history": []}
            if "history" not in manifest: manifest["history"] = []
            
            manifest["history"].append({
                "attempt": attempt,
                "error": clean_error,
                "status": "failed"
            })
            
            # IMPORTANT: Set repairing to True so frontend shows the analysis phase
            manifest["repairing"] = True
            manifest["last_error"] = clean_error
            
            scene.manifest = manifest
            scene.error_message = f"Attempt {attempt} failed: {clean_error}"
            scene.save()

            if attempt < MAX_RETRIES:
                scene.status = 'generating_code'
                scene.save()

                fix_prompt = (
                    f"The code you generated has an error when executed by Manim.\n\n"
                    f"ERROR: {clean_error}\n\n"
                    f"Here is the failing code:\n```python\n{current_code}\n```\n\n"
                    f"Fix this error and return the complete corrected code."
                )

                retry_history = history.copy()
                retry_history.append({"role": "user", "content": scene.prompt})
                retry_history.append({"role": "model", "content": current_code})

                structured_fix = get_llm_response(prompt=fix_prompt, history=retry_history, target_model=scene.target_model)
                
                if not structured_fix.is_animation or not structured_fix.code:
                    break
                
                fixed_code = clean_code(structured_fix.code)
                current_code = fixed_code
                scene.code = fixed_code
                scene.status = 'rendering'
                scene.save()

        # All retries exhausted
        scene.status = 'error'
        scene.error_message = (
            "The AI was unable to generate a working animation after multiple attempts. "
            "Please try simplifying your prompt."
        )
        scene.save()

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Task error for scene {scene_id}: {error_msg}")
        
        if "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
            error_msg = "Google Gemini API Token Limit Exceeded. Please wait a short while."
        else:
            error_msg = "An unexpected error occurred while generating your animation."
        
        scene.status = 'error'
        scene.error_message = error_msg
        scene.save()

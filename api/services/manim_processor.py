import sys
from api.services.utils import code_validator
import tempfile
import os
import subprocess
import shutil
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def execute_manim_code(code, scene_id, quality="720p"):
    """
    Execute the provided Manim code and render the animation.
    """
    is_valid, error_msg = code_validator(code)
    if not is_valid:
        return None, f"Code validation failed: {error_msg}"
    
    temp_dir = tempfile.mkdtemp(prefix=f"manim_scene_{scene_id}_")
    code_file = os.path.join(temp_dir, f"scene_{scene_id}.py")

    try:
        if "class" not in code:
            return None, "Invalid Manim code: No class definition found."
        if "def construct(self):" not in code:
            return None, "Invalid Manim code: No construct method found."
        
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        quality_flags = {
            "480p": ["-ql"],
            "720p": ["-qm"],
            "1080p": ["-qh"],
            "4k": ["-qk"]
        }
        quality_args = quality_flags.get(quality, ["-qm"])

        cmd = [
            sys.executable,
            "-m",
            "manim",
            *quality_args,
            code_file,
            "--output_file", f"scene_{scene_id}"
        ]

        result = subprocess.run(
            cmd,
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=300,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode == 0:
            media_dir = os.path.join(temp_dir, "media", "videos")
            if not os.path.exists(media_dir):
                return None, f"No video file generated. Manim output: {result.stdout}"
            
            for root, dirs, files in os.walk(media_dir):
                for file in files:
                    if file.endswith(".mp4"):
                        video_path = os.path.join(root, file)
                        
                        output_dir = os.path.join(settings.MEDIA_ROOT, 'videos')
                        os.makedirs(output_dir, exist_ok=True)

                        final_path = os.path.join(output_dir, f"scene_{scene_id}.mp4")
                        shutil.copy2(video_path, final_path)

                        return f"/media/videos/scene_{scene_id}.mp4", None
                        
            return None, f"No mp4 file found. Manim output: {result.stdout}"
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            return None, f"Manim execution failed: {error_msg}"
    except subprocess.TimeoutExpired:
        return None, "Manim execution timed out (5 minutes)."
    except Exception as e:
        logger.error(f"Execution error: {str(e)}")
        return None, f"Execution error: {str(e)}"
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to delete temp directory {temp_dir}: {str(e)}")

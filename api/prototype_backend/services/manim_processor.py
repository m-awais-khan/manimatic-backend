from backend.utils import code_validator
import tempfile
import os
import subprocess
import shutil
from config import OUTPUT_DIR

def execute_manim_code(code, scene_id, quality="720p"):
    """
    Execute the provided Manim code and render the animation.
    
    Args:
        code (str): The Manim Python code to execute.
        scene_id (str): Unique identifier for the scene.
        quality (str): Video quality setting.
        background_color (str): Background color in hex format.
        text_color (str): Text color in hex format.
    Returns:
        tuple: (video_path (str) or None, error_message (str) or None)
    """

    # Check code validity
    is_valid, error_msg = code_validator(code)
    if not is_valid:
        return None, f"Code validation failed: {error_msg}"
    
    # Create a temporary directory for this scene
    temp_dir = tempfile.mkdtemp(prefix=f"manim_scene_{scene_id}_")
    code_file = os.path.join(temp_dir, f"scene_{scene_id}.py")

    try:
        # Validate code before writing
        if "class" not in code:
            return None, "Invalid Manim code: No class definition found."
        if "def construct(self):" not in code:
            return None, "Invalid Manim code: No construct method found."
        
        # Write the code to a temporary Python file
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Quality mapping
        quality_flags = {
            "480p": ["-ql"],   # low quality (854x480)
            "720p": ["-qm"],   # medium quality (1280x720)
            "1080p": ["-qh"],  # high quality (1920x1080)
            "4k": ["-qk"]      # 4k quality
        }
        quality_args = quality_flags.get(quality, ["-qm"])  # fallback: 720p

        # Build manim command
        cmd = [
            "manim",
            *quality_args,
            code_file,
            "--output_file", f"scene_{scene_id}"
        ]

        # Run the command with better error handling
        result = subprocess.run(
            cmd,
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode == 0:
            # Locate the rendered video file
            media_dir = os.path.join(temp_dir, "media", "videos")

            if not os.path.exists(media_dir):
                return None, f"No video file generated. Manim output: {result.stdout}"
            for root, dirs, files in os.walk(media_dir):
                for file in files:
                    if file.endswith(".mp4"):
                        video_path = os.path.join(root, file)
                        
                        # Create output directory if it doesn't exist
                        output_dir = OUTPUT_DIR
                        os.makedirs(output_dir, exist_ok=True)

                        # Copy video to output directory
                        final_path = os.path.join(output_dir, f"scene_{scene_id}.mp4")
                        shutil.copy2(video_path, final_path)

                        return final_path, None
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            return None, f"Manim execution failed: {error_msg}"
    except subprocess.TimeoutExpired:
        return None, "Manim execution timed out (5 minutes)."
    except Exception as e:
        return None, f"Execution error: {str(e)}"
    finally:
        # Clean up temporary directory
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"Warning: Failed to delete temp directory {temp_dir}: {str(e)}")
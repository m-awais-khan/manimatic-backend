"""Background task: run deterministic playground code through Manim (no LLM)."""
import logging

from api.models import Scene
from api.services.manim_processor import execute_manim_code

logger = logging.getLogger(__name__)


def compile_and_render_task(scene_id, quality: str = "720p") -> None:
    try:
        scene = Scene.objects.get(id=scene_id)
    except Scene.DoesNotExist:
        logger.error("Playground scene %s not found", scene_id)
        return

    code = scene.code or ""
    if not code.strip():
        scene.status = "error"
        scene.error_message = "No compiled code on scene."
        scene.save(update_fields=["status", "error_message"])
        return

    scene.status = "rendering"
    scene.save(update_fields=["status"])

    video_url, error = execute_manim_code(code, str(scene_id), quality=quality)

    if not error:
        scene.status = "completed"
        scene.video_path = video_url
        scene.error_message = None
        scene.save(update_fields=["status", "video_path", "error_message"])
        logger.info("Playground scene %s rendered OK", scene_id)
        return

    scene.status = "error"
    scene.error_message = (error or "Manim render failed")[:2000]
    scene.save(update_fields=["status", "error_message"])
    logger.warning("Playground scene %s failed: %s", scene_id, scene.error_message)

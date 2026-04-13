import subprocess
import os
import json
from django.conf import settings
import uuid
import logging

logger = logging.getLogger(__name__)

TRANSITION_DURATION = 0.5  # seconds


def _get_video_duration(path):
    """Get video duration in seconds using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data['format']['duration'])
    except Exception as e:
        logger.warning(f"Could not get duration for {path}: {e}")
    return 5.0  # fallback


def _stitch_with_cut(video_paths, output_path):
    """Fast concat demuxer — no re-encoding, instant."""
    output_dir = os.path.dirname(output_path)
    concat_file = os.path.join(output_dir, f"_concat_{uuid.uuid4().hex[:6]}.txt")
    
    with open(concat_file, 'w') as f:
        for path in video_paths:
            escaped = path.replace('\\', '/').replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    
    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', concat_file,
        '-c', 'copy',
        output_path
    ]
    
    logger.info(f"Cut stitch: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    
    try: os.remove(concat_file)
    except: pass
    
    return result


def _stitch_with_transition(video_paths, output_path, transition_type):
    """
    Use ffmpeg xfade filter for transitions between clips. 
    Requires re-encoding but uses ultrafast preset for speed.
    
    The xfade filter chains: 
    For n videos, we need n-1 xfade filters chained together.
    """
    n = len(video_paths)
    
    # Get durations of each video
    durations = [_get_video_duration(p) for p in video_paths]
    
    # Build input args
    input_args = []
    for path in video_paths:
        input_args.extend(['-i', path])
    
    if n == 2:
        # Simple case: just one xfade between two inputs
        offset = max(0, durations[0] - TRANSITION_DURATION)
        filter_complex = (
            f"[0:v][1:v]xfade=transition={transition_type}"
            f":duration={TRANSITION_DURATION}:offset={offset}[outv]"
        )
    else:
        # Chain xfade filters for 3+ videos
        filters = []
        # Accumulated offset tracking
        # After each xfade, the output is shorter by TRANSITION_DURATION
        accumulated_duration = durations[0]
        
        # First xfade: [0:v] and [1:v]
        offset = max(0, accumulated_duration - TRANSITION_DURATION)
        filters.append(
            f"[0:v][1:v]xfade=transition={transition_type}"
            f":duration={TRANSITION_DURATION}:offset={offset}[v1]"
        )
        accumulated_duration = offset + durations[1]  # new total after xfade
        
        # Chain remaining videos
        for i in range(2, n):
            prev_label = f"v{i-1}"
            offset = max(0, accumulated_duration - TRANSITION_DURATION)
            
            if i == n - 1:
                # Last one outputs [outv]
                filters.append(
                    f"[{prev_label}][{i}:v]xfade=transition={transition_type}"
                    f":duration={TRANSITION_DURATION}:offset={offset}[outv]"
                )
            else:
                out_label = f"v{i}"
                filters.append(
                    f"[{prev_label}][{i}:v]xfade=transition={transition_type}"
                    f":duration={TRANSITION_DURATION}:offset={offset}[{out_label}]"
                )
            accumulated_duration = offset + durations[i]
        
        filter_complex = ";".join(filters)
    
    cmd = [
        'ffmpeg', '-y',
        *input_args,
        '-filter_complex', filter_complex,
        '-map', '[outv]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-an',
        output_path
    ]
    
    logger.info(f"Transition stitch ({transition_type}): {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result


def stitch_videos_task(stitched_video_id, transition='cut'):
    """
    Background task: stitch multiple videos together.
    - 'cut': uses fast concat demuxer (no re-encoding)
    - other transitions: uses ffmpeg xfade filter
    """
    from api.models import StitchedVideo
    
    try:
        sv = StitchedVideo.objects.get(id=stitched_video_id)
    except StitchedVideo.DoesNotExist:
        logger.error(f"StitchedVideo {stitched_video_id} not found.")
        return
    
    try:
        sv.status = 'processing'
        sv.save()
        
        video_urls = sv.source_video_paths
        
        if len(video_urls) < 2:
            sv.status = 'error'
            sv.error_message = 'Need at least 2 videos to stitch.'
            sv.save()
            return
        
        # Convert URLs to absolute filesystem paths or keep HTTP URLs
        video_paths = []
        for url in video_urls:
            if url.startswith('/media/'):
                path = os.path.join(settings.BASE_DIR, url.lstrip('/'))
                path = os.path.normpath(path)
                video_paths.append(path)
            elif url.startswith('http://') or url.startswith('https://'):
                video_paths.append(url)
            else:
                video_paths.append(os.path.normpath(url))
        
        # Verify all local files exist
        for p in video_paths:
            if p.startswith('http://') or p.startswith('https://'):
                continue
            if not os.path.exists(p):
                sv.status = 'error'
                sv.error_message = f'Video file not found: {os.path.basename(p)}'
                sv.save()
                logger.error(f"Video not found: {p}")
                return
        
        import tempfile
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile
        
        output_filename = f"stitched_{uuid.uuid4().hex[:8]}.mp4"
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, output_filename)

        # Choose stitching method
        if transition == 'cut':
            result = _stitch_with_cut(video_paths, output_path)
        else:
            result = _stitch_with_transition(video_paths, output_path, transition)

        if result.returncode == 0:
            with open(output_path, 'rb') as f:
                saved_path = default_storage.save(f"stitched/{output_filename}", ContentFile(f.read()))
            sv.video_path = default_storage.url(saved_path)
            
            try: os.remove(output_path)
            except: pass
            
            sv.status = 'completed'
            logger.info(f"Stitch completed: {sv.video_path}")
        else:
            sv.status = 'error'
            sv.error_message = result.stderr[:500] if result.stderr else 'FFmpeg failed'
            logger.error(f"FFmpeg stderr: {result.stderr}")
        
        sv.save()

    except Exception as e:
        logger.error(f"Stitch error for {stitched_video_id}: {str(e)}")
        sv.status = 'error'
        sv.error_message = str(e)[:500]
        sv.save()

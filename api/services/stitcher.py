import subprocess
import os
import json
import urllib.request
import tempfile as _tempfile
from django.conf import settings
import uuid
import logging
import re

logger = logging.getLogger(__name__)

TRANSITION_DURATION = 0.5  # seconds
ALLOWED_TRANSITIONS = {
    'fade', 'fadeblack', 'fadewhite', 'dissolve', 'wipeleft', 'wiperight',
    'wipeup', 'wipedown', 'slideleft', 'slideright', 'slideup', 'slidedown',
    'circleopen', 'circleclose', 'smoothleft', 'smoothright'
}

try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception as e:
    logger.warning(f"imageio_ffmpeg not found, falling back to system ffmpeg: {e}")
    FFMPEG_EXE = 'ffmpeg'


def _get_video_duration(path):
    """Get video duration in seconds using ffprobe."""
    # First try ffprobe
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
    except Exception:
        pass
        
    # Fallback to parsing ffmpeg stderr
    try:
        res = subprocess.run([FFMPEG_EXE, '-i', path], capture_output=True, text=True, timeout=30)
        match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', res.stderr)
        if match:
            return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    except Exception as e:
        logger.warning(f"Could not parse duration for {path} using ffmpeg: {e}")
        
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
        FFMPEG_EXE, '-y',
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


def _stitch_with_transition(video_paths, output_path, transition_type, transition_sequence=None, output_settings=None):
    """
    Use ffmpeg xfade filter for transitions between clips. 
    Requires re-encoding but uses ultrafast preset for speed.
    
    The xfade filter chains: 
    For n videos, we need n-1 xfade filters chained together.
    """
    n = len(video_paths)
    
    output_settings = output_settings or {}
    width = int(output_settings.get('width') or 1280)
    height = int(output_settings.get('height') or 720)
    fps = int(output_settings.get('fps') or 30)
    crf = str(output_settings.get('crf') or 23)
    transition_sequence = transition_sequence or []

    # Get durations of each video
    durations = [_get_video_duration(p) for p in video_paths]
    
    # Build input args
    input_args = []
    for path in video_paths:
        input_args.extend(['-i', path])
        
    filters = []
    
    # Scale and normalize all inputs to a shared frame spec.
    # This prevents the "parameters do not match" error in xfade.
    for i in range(n):
        filters.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p[v{i}_norm]"
        )

    def transition_at(index):
        transition = transition_sequence[index] if index < len(transition_sequence) else transition_type
        if transition == 'cut':
            transition = 'fade'
        return transition if transition in ALLOWED_TRANSITIONS else 'fade'
    
    if n == 2:
        # Simple case: just one xfade between two inputs
        offset = max(0, durations[0] - TRANSITION_DURATION)
        filters.append(
            f"[v0_norm][v1_norm]xfade=transition={transition_at(0)}"
            f":duration={TRANSITION_DURATION}:offset={offset}[outv]"
        )
    else:
        # Chain xfade filters for 3+ videos
        accumulated_duration = durations[0]
        
        # First xfade: [v0_norm] and [v1_norm]
        offset = max(0, accumulated_duration - TRANSITION_DURATION)
        filters.append(
            f"[v0_norm][v1_norm]xfade=transition={transition_at(0)}"
            f":duration={TRANSITION_DURATION}:offset={offset}[xf1]"
        )
        accumulated_duration = offset + durations[1]  # new total after xfade
        
        # Chain remaining videos
        for i in range(2, n):
            prev_label = f"xf{i-1}"
            offset = max(0, accumulated_duration - TRANSITION_DURATION)
            
            if i == n - 1:
                # Last one outputs [outv]
                filters.append(
                    f"[{prev_label}][v{i}_norm]xfade=transition={transition_at(i - 1)}"
                    f":duration={TRANSITION_DURATION}:offset={offset}[outv]"
                )
            else:
                out_label = f"xf{i}"
                filters.append(
                    f"[{prev_label}][v{i}_norm]xfade=transition={transition_at(i - 1)}"
                    f":duration={TRANSITION_DURATION}:offset={offset}[{out_label}]"
                )
            accumulated_duration = offset + durations[i]
            
    filter_complex = ";".join(filters)
    
    cmd = [
        FFMPEG_EXE, '-y',
        *input_args,
        '-filter_complex', filter_complex,
        '-map', '[outv]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', crf,
        '-an',
        output_path
    ]
    
    logger.info(f"Transition stitch ({transition_type}): {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result


def _clamp_float(value, default, min_value=None, max_value=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if min_value is not None:
        number = max(min_value, number)
    if max_value is not None:
        number = min(max_value, number)
    return number


def _safe_output_settings(raw):
    raw = raw or {}
    preset = raw.get('preset') or '720p'
    presets = {
        '480p': (854, 480),
        '720p': (1280, 720),
        '1080p': (1920, 1080),
    }
    width, height = presets.get(preset, presets['720p'])
    fps = int(_clamp_float(raw.get('fps'), 30, 15, 60))
    crf = int(_clamp_float(raw.get('crf'), 23, 18, 30))
    return {'width': width, 'height': height, 'fps': fps, 'crf': crf}


def _prepare_clip(clip, source_path, output_path, output_settings):
    """Render one timeline clip to a normalized temp file."""
    speed = _clamp_float(clip.get('speed'), 1.0, 0.25, 4.0)
    trim_start = _clamp_float(clip.get('trim_start'), 0.0, 0.0, None)
    trim_end = _clamp_float(clip.get('trim_end'), 0.0, 0.0, None)
    duration = _get_video_duration(source_path)
    usable_duration = max(0.1, duration - trim_start - trim_end)

    input_args = []
    if trim_start > 0:
        input_args.extend(['-ss', str(trim_start)])
    input_args.extend(['-i', source_path, '-t', str(usable_duration)])

    vf = (
        f"setpts=PTS/{speed},"
        f"scale={output_settings['width']}:{output_settings['height']}:force_original_aspect_ratio=decrease,"
        f"pad={output_settings['width']}:{output_settings['height']}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={output_settings['fps']},format=yuv420p"
    )

    cmd = [
        FFMPEG_EXE, '-y',
        *input_args,
        '-vf', vf,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', str(output_settings['crf']),
        '-an',
        output_path
    ]
    logger.info(f"Prepare clip: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)


def _prepare_edit_plan(video_paths, edit_plan, output_settings):
    clips = edit_plan.get('clips') if edit_plan else None
    if not clips:
        clips = [{'video_path': path} for path in video_paths]

    prepared_paths = []
    temp_paths = []
    temp_dir = _tempfile.gettempdir()

    for index, source_path in enumerate(video_paths):
        clip = clips[index] if index < len(clips) and isinstance(clips[index], dict) else {}
        clip_output = os.path.join(temp_dir, f"clip_{uuid.uuid4().hex[:8]}_{index}.mp4")
        result = _prepare_clip(clip, source_path, clip_output, output_settings)
        if result.returncode != 0:
            for temp_path in temp_paths:
                try: os.remove(temp_path)
                except: pass
            return None, temp_paths, result
        prepared_paths.append(clip_output)
        temp_paths.append(clip_output)

    return prepared_paths, temp_paths, None


def _collapse_cut_groups(video_paths, transition_sequence, fallback_transition):
    effective = []
    for index in range(max(0, len(video_paths) - 1)):
        transition = transition_sequence[index] if index < len(transition_sequence) else fallback_transition
        effective.append(transition)

    groups = [[video_paths[0]]]
    group_transitions = []
    for index, transition in enumerate(effective):
        if transition == 'cut':
            groups[-1].append(video_paths[index + 1])
        else:
            group_transitions.append(transition)
            groups.append([video_paths[index + 1]])

    rendered_groups = []
    temp_paths = []
    temp_dir = _tempfile.gettempdir()
    for index, group in enumerate(groups):
        if len(group) == 1:
            rendered_groups.append(group[0])
            continue

        group_output = os.path.join(temp_dir, f"group_{uuid.uuid4().hex[:8]}_{index}.mp4")
        result = _stitch_with_cut(group, group_output)
        if result.returncode != 0:
            for temp_path in temp_paths:
                try: os.remove(temp_path)
                except: pass
            return None, group_transitions, temp_paths, result

        rendered_groups.append(group_output)
        temp_paths.append(group_output)

    return rendered_groups, group_transitions, temp_paths, None


def stitch_videos_task(stitched_video_id, transition='cut', edit_plan=None):
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
        
        # Convert URLs to absolute filesystem paths.
        # S3/HTTPS URLs must be downloaded to temp files because
        # ffmpeg's concat demuxer cannot read remote HTTP URLs.
        video_paths = []
        _downloaded_temps = []  # track downloaded temp files for cleanup

        for url in video_urls:
            if url.startswith('http://') or url.startswith('https://'):
                # Download S3/remote video to a local temp file
                tmp_fd, tmp_path = _tempfile.mkstemp(suffix='.mp4')
                os.close(tmp_fd)
                logger.info(f"Downloading remote video: {url} -> {tmp_path}")
                try:
                    urllib.request.urlretrieve(url, tmp_path)
                except Exception as dl_err:
                    sv.status = 'error'
                    sv.error_message = f'Failed to download video: {str(dl_err)}'
                    sv.save()
                    logger.error(f"Download failed for {url}: {dl_err}")
                    for t in _downloaded_temps:
                        try: os.remove(t)
                        except: pass
                    return
                video_paths.append(tmp_path)
                _downloaded_temps.append(tmp_path)
            elif url.startswith('/media/'):
                path = os.path.join(settings.BASE_DIR, url.lstrip('/'))
                path = os.path.normpath(path)
                video_paths.append(path)
            else:
                video_paths.append(os.path.normpath(url))
        
        # Verify all local files exist
        for p in video_paths:
            if not os.path.exists(p):
                sv.status = 'error'
                sv.error_message = f'Video file not found: {os.path.basename(p)}'
                sv.save()
                logger.error(f"Video not found: {p}")
                for t in _downloaded_temps:
                    try: os.remove(t)
                    except: pass
                return
        
        import tempfile
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile
        
        output_settings = _safe_output_settings((edit_plan or {}).get('output'))
        output_filename = f"stitched_{uuid.uuid4().hex[:8]}.mp4"
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, output_filename)
        temp_render_paths = []

        has_clip_edits = bool(edit_plan and edit_plan.get('clips'))
        transition_sequence = (edit_plan or {}).get('transitions') or []

        if has_clip_edits:
            prepared_paths, temp_render_paths, prep_error = _prepare_edit_plan(video_paths, edit_plan, output_settings)
            if prep_error is not None:
                sv.status = 'error'
                sv.error_message = prep_error.stderr[:500] if prep_error.stderr else 'FFmpeg failed while preparing clips'
                sv.save()
                for t in _downloaded_temps + temp_render_paths:
                    try: os.remove(t)
                    except: pass
                return
            video_paths = prepared_paths

        # Choose stitching method
        effective_transitions = [
            transition_sequence[i] if i < len(transition_sequence) else transition
            for i in range(max(0, len(video_paths) - 1))
        ]
        all_cuts = all(t == 'cut' for t in effective_transitions)
        if all_cuts:
            result = _stitch_with_cut(video_paths, output_path)
        else:
            result = _stitch_with_transition(video_paths, output_path, transition, effective_transitions, output_settings)

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

        # Cleanup any downloaded temp files
        for t in _downloaded_temps + temp_render_paths:
            try: os.remove(t)
            except: pass

    except Exception as e:
        logger.error(f"Stitch error for {stitched_video_id}: {str(e)}")
        sv.status = 'error'
        sv.error_message = str(e)[:500]
        sv.save()

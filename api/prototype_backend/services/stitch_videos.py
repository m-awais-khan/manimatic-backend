import subprocess

def video_stitcher(video_paths, output_path, transition_effect="fade"):
    """
    Stitch multiple videos together with various transition effects
    
    Args:
        video_paths (list): List of paths to video files
        output_path (str): Path where the output video will be saved
        transition_effect (str): Type of transition - "fade", "cut", "slide", "zoom"
        transition_duration (float): Duration of transition in seconds (ignored for "cut")
    
    Returns:
        tuple: (success: bool, message: str)
    """
    
    if len(video_paths) < 2:
        return False, "Need at least 2 videos to stitch."
    
    try:
        input_parts = []

        for path in video_paths:
            input_parts.extend(['-i', path])
        
        # Build the stream labels: [0:v:0][1:v:0]...
        labels = ''.join(f"[{i}:v:0]" for i in range(len(video_paths)))

        # Simple concatenation for now (later can add transitions)
        # concat: n=<number of inputs>, output 1 video stream, no audio
        filter_complex = f"{labels}concat=n={len(video_paths)}:v=1:a=0[outv]"

        cmd = [
            'ffmpeg',
            "-y",  # Overwrite output files without asking
            *input_parts,
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            return True, None
        else:
            return False, result.stderr
        
    except Exception as e:
        return False, str(e)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authtoken.models import Token
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.conf import settings as django_settings
from .models import Scene, Chat, StitchedVideo, UserProfile, DataTrainingOptOut
from .serializers import SceneSerializer, ChatSerializer, StitchedVideoSerializer
import threading
import requests
import os
import shutil
import logging
import json
import random
from pathlib import Path
from .services.generator import generate_scene_task
from .services.stitcher import stitch_videos_task
from .services.prompt_enhancer import enhance_prompt


logger = logging.getLogger(__name__)

# ── Dataset JSON loader (cached at module level) ──────────────

_DATASET_CACHE = None

def _load_dataset():
    """
    Load manim-dataset-viewer.json from the frontend/public directory.
    Result is cached in the module-level _DATASET_CACHE so the file
    is only read from disk once per server process.
    """
    global _DATASET_CACHE
    if _DATASET_CACHE is None:
        # BASE_DIR is the backend/ folder; the JSON sits one level up in frontend/public/
        json_path = Path(django_settings.BASE_DIR).parent / 'frontend' / 'public' / 'manim-dataset-viewer.json'
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            # The JSON root is either a list or { "examples": [...] }
            if isinstance(raw, list):
                _DATASET_CACHE = raw
            else:
                _DATASET_CACHE = raw.get('examples', [])
            logger.info('Dataset loaded: %d entries', len(_DATASET_CACHE))
        except Exception as e:
            logger.error('Failed to load dataset JSON: %s', e)
            _DATASET_CACHE = []
    return _DATASET_CACHE


# ── S3 Debug View (temporary — remove in prod) ───────────────

class S3DebugView(APIView):
    """Quick endpoint to verify S3 config on Render without digging through logs."""
    permission_classes = [AllowAny]

    def get(self, request):
        from django.core.files.storage import default_storage
        return Response({
            'USE_S3': getattr(django_settings, 'USE_S3', False),
            'storage_backend': default_storage.__class__.__name__,
            'bucket': getattr(django_settings, 'AWS_STORAGE_BUCKET_NAME', 'N/A'),
            'endpoint': getattr(django_settings, 'AWS_S3_ENDPOINT_URL', 'N/A'),
            'media_url': django_settings.MEDIA_URL,
        })

# ── Dataset Suggestions View ───────────────────────────────────

class DatasetSuggestionsView(APIView):
    """
    GET /api/suggestions/?count=4
    Returns `count` (default 4, max 5) random dataset entries whose
    video file exists, for use as suggestion chips on the new-chat screen.
    No authentication required.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            count = min(int(request.query_params.get('count', 4)), 5)
        except (ValueError, TypeError):
            count = 4

        dataset = _load_dataset()
        pool = [e for e in dataset if e.get('video_exists', False)]

        if not pool:
            return Response([], status=status.HTTP_200_OK)

        picks = random.sample(pool, min(count, len(pool)))
        results = [
            {
                'id': e['id'],
                'instruction': e['instruction'],
                'category': e.get('category', ''),
                'complexity': e.get('complexity', ''),
                'video_path': e['video_path'],
            }
            for e in picks
        ]
        return Response(results)


# ── Dataset Scene (instant, no AI) ───────────────────────────

class DatasetSceneView(APIView):
    """
    POST /api/scenes/from-dataset/
    Body: { "dataset_id": "0016-bubblesortanimation" }

    Creates a Chat + Scene record pre-populated from the dataset entry
    (status=completed, code and video_path set immediately). The response
    has the same shape as GenerateSceneView so the frontend can reuse the
    exact same update logic.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile

        dataset_id = request.data.get('dataset_id', '').strip()
        if not dataset_id:
            return Response(
                {'error': '"dataset_id" is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        dataset = _load_dataset()
        entry = next((e for e in dataset if e.get('id') == dataset_id), None)
        if entry is None:
            return Response(
                {'error': f'Dataset entry "{dataset_id}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        instruction = entry['instruction']
        code = entry.get('output', '')
        dataset_video_path = entry['video_path']  # e.g. /dataset-videos/0016-bubblesortanimation.mp4

        # Trim title to 60 chars for a clean sidebar label
        title = (instruction[:57] + '...') if len(instruction) > 60 else instruction

        # Create the chat first so we have an ID to name the video file
        chat = Chat.objects.create(title=title, user=request.user)

        # Create scene with a placeholder video_path — we'll update after copying
        scene = Scene.objects.create(
            chat=chat,
            prompt=instruction,
            code=code,
            video_path=None,
            status='completed',
            target_model='dataset',
        )

        # ── Copy the dataset video into the user's own media storage ──────
        # Source: frontend/public/dataset-videos/<filename>.mp4 (local disk)
        video_filename = dataset_video_path.lstrip('/').split('/')[-1]  # e.g. 0016-bubblesortanimation.mp4
        src_path = (
            Path(django_settings.BASE_DIR).parent
            / 'frontend' / 'public' / 'dataset-videos'
            / video_filename
        )
        storage_key = f'videos/scene_{scene.id}.mp4'

        try:
            with open(src_path, 'rb') as f:
                saved_name = default_storage.save(storage_key, ContentFile(f.read()))

            # Works for both local (returns /media/...) and S3 (returns https://...)
            stored_video_path = default_storage.url(saved_name)
            scene.video_path = stored_video_path
            scene.save(update_fields=['video_path'])
            logger.info(
                'Dataset video copied to storage: user=%s entry=%s stored_as=%s',
                request.user.email, dataset_id, saved_name
            )
        except FileNotFoundError:
            logger.error('Dataset video not found on disk: %s', src_path)
            # Fall back to direct dataset path rather than leaving video_path null
            scene.video_path = dataset_video_path
            scene.save(update_fields=['video_path'])
        except Exception as e:
            logger.error('Failed to copy dataset video for scene %s: %s', scene.id, e)
            scene.video_path = dataset_video_path
            scene.save(update_fields=['video_path'])

        serializer = SceneSerializer(scene)
        logger.info(
            'Dataset scene created: user=%s entry=%s scene=%s',
            request.user.email, dataset_id, scene.id
        )
        return Response(
            {'scene': serializer.data, 'chat_id': str(chat.id)},
            status=status.HTTP_201_CREATED
        )



# ── Auth Views ──────────────────────────────────────────────

def _delete_storage_file(video_path):
    """
    Delete a video from storage (works for both S3 and local filesystem).
    Accepts either:
      - A full S3/HTTPS URL: https://<project>.supabase.co/storage/v1/object/public/<bucket>/videos/scene_xyz.mp4
      - A local media path:  /media/videos/scene_xyz.mp4
    Extracts the relative storage key and calls default_storage.delete().
    """
    from django.core.files.storage import default_storage
    from django.conf import settings as dj_settings

    if not video_path:
        return

    try:
        bucket = getattr(dj_settings, 'AWS_STORAGE_BUCKET_NAME', '')

        if video_path.startswith('http://') or video_path.startswith('https://'):
            # S3 URL — extract the key after /object/public/<bucket>/
            # e.g. https://xxx.supabase.co/storage/v1/object/public/manimatic-media/videos/scene_abc.mp4
            # → videos/scene_abc.mp4
            marker = f'/object/public/{bucket}/'
            if marker in video_path:
                storage_key = video_path.split(marker, 1)[1]
            else:
                # Fallback: take everything after the last known prefix
                storage_key = video_path.split('/')[-1]  # just the filename
        else:
            # Local path like /media/videos/scene_xyz.mp4 → videos/scene_xyz.mp4
            storage_key = video_path.lstrip('/').removeprefix('media/').lstrip('/')

        logger.info(f"Deleting storage key: {storage_key}")
        default_storage.delete(storage_key)
    except Exception as e:
        logger.warning(f"Could not delete storage file '{video_path}': {e}")


class GoogleAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get('id_token')
        if not id_token:
            return Response({'error': 'id_token is required'}, status=status.HTTP_400_BAD_REQUEST)

        # Verify token with Google
        try:
            resp = requests.get(
                f'https://oauth2.googleapis.com/tokeninfo?id_token={id_token}',
                timeout=10
            )
            if resp.status_code != 200:
                return Response({'error': 'Invalid token'}, status=status.HTTP_401_UNAUTHORIZED)

            google_data = resp.json()

            # Verify audience matches our client ID
            if google_data.get('aud') != django_settings.GOOGLE_CLIENT_ID:
                return Response({'error': 'Token audience mismatch'}, status=status.HTTP_401_UNAUTHORIZED)

            google_id = google_data.get('sub')
            email = google_data.get('email', '')
            name = google_data.get('name', email.split('@')[0])
            picture = google_data.get('picture', '')

        except Exception as e:
            return Response({'error': f'Token verification failed: {str(e)}'}, status=status.HTTP_401_UNAUTHORIZED)

        # Find or create user
        try:
            profile = UserProfile.objects.get(google_id=google_id)
            user = profile.user
            # Update profile info (might have changed)
            profile.display_name = name
            profile.profile_picture = picture
            profile.save()
        except UserProfile.DoesNotExist:
            # Create new user
            username = f'google_{google_id}'
            user = User.objects.create_user(username=username, email=email)
            profile = UserProfile.objects.create(
                user=user,
                google_id=google_id,
                display_name=name,
                profile_picture=picture
            )

        # Get or create token
        token, _ = Token.objects.get_or_create(user=user)

        return Response({
            'token': token.key,
            'profile': {
                'email': user.email,
                'display_name': profile.display_name,
                'profile_picture': profile.profile_picture,
            }
        })


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.profile
        except UserProfile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'email': request.user.email,
            'display_name': profile.display_name,
            'profile_picture': profile.profile_picture,
        })

    def delete(self, request):
        """Delete account and ALL associated data including S3 files."""
        user = request.user
        user.delete()  # Cascades to Profile, Chats, Scenes, StitchedVideos (and signals handle files)
        return Response({'message': 'Account deleted'}, status=status.HTTP_204_NO_CONTENT)


class DataTrainingConsentView(APIView):
    """
    GET  /api/auth/training-consent/
        Returns the current consent state for the authenticated user.
        { "consented": true }   → user allows data to be used for training
        { "consented": false }  → user has opted out

    POST /api/auth/training-consent/
        Body: { "consented": true | false }
        Opt the user back in (deletes the opt-out row) or opt them out
        (creates the opt-out row).  Idempotent.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        opted_out = DataTrainingOptOut.objects.filter(user=request.user).exists()
        return Response({'consented': not opted_out})

    def post(self, request):
        consented = request.data.get('consented')
        if consented is None:
            return Response(
                {'error': '"consented" field is required (true or false)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if consented:
            # User is turning consent ON → remove their opt-out record if it exists
            deleted_count, _ = DataTrainingOptOut.objects.filter(user=request.user).delete()
            action = 'opted_in'
        else:
            # User is turning consent OFF → ensure an opt-out record exists
            _, created = DataTrainingOptOut.objects.get_or_create(user=request.user)
            action = 'opted_out_created' if created else 'opted_out_already'

        logger.info(
            'Training consent change: user=%s action=%s',
            request.user.email,
            action
        )
        return Response({'consented': bool(consented), 'action': action})


class WipeDataView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        """Wipe all user data but keep the account."""
        user = request.user

        # Delete all chats (cascades to scenes, signals handle files)
        Chat.objects.filter(user=user).delete()

        # Delete all stitched videos (signals handle files)
        StitchedVideo.objects.filter(user=user).delete()



        return Response({'message': 'All data wiped'}, status=status.HTTP_204_NO_CONTENT)


# ── Chat Views (user-scoped) ───────────────────────────────

class ChatListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        chats = Chat.objects.filter(user=request.user).order_by('-updated_at')
        serializer = ChatSerializer(chats, many=True)
        return Response(serializer.data)

class ChatDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk, user=request.user)
        serializer = ChatSerializer(chat)
        return Response(serializer.data)
        
    def delete(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk, user=request.user)
        chat.delete() # Signals handle file deletion
        return Response(status=status.HTTP_204_NO_CONTENT)

class GenerateSceneView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        chat_id = request.data.get('chat_id')
        prompt = request.data.get('prompt', '')
        
        if chat_id:
            chat = get_object_or_404(Chat, id=chat_id, user=request.user)
        else:
            title = prompt[:30] + '...' if len(prompt) > 30 else prompt
            chat = Chat.objects.create(title=title, user=request.user)

        data = request.data.copy()
        
        if chat:
            data['chat'] = chat.id

        serializer = SceneSerializer(data=data)
        if serializer.is_valid():
            scene = serializer.save(status='pending', chat=chat)
            quality = request.data.get('quality', '720p')
            threading.Thread(target=generate_scene_task, args=(scene.id, quality)).start()
            return Response({'scene': serializer.data, 'chat_id': chat.id}, status=status.HTTP_202_ACCEPTED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SceneStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        scene = get_object_or_404(Scene, pk=pk)
        serializer = SceneSerializer(scene)
        return Response(serializer.data)

# ── Stitcher Views (user-scoped) ───────────────────────────

class StitchVideosView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        video_paths = request.data.get('video_paths', [])
        title = request.data.get('title', 'Stitched Video')
        transition = request.data.get('transition', 'cut')
        
        if not video_paths or len(video_paths) < 2:
            return Response({'error': 'Need at least 2 videos to stitch.'}, status=status.HTTP_400_BAD_REQUEST)
        
        sv = StitchedVideo.objects.create(
            title=title,
            source_video_paths=video_paths,
            status='pending',
            user=request.user
        )
        
        threading.Thread(target=stitch_videos_task, args=(sv.id, transition)).start()
        
        serializer = StitchedVideoSerializer(sv)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

class StitchedVideoListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        videos = StitchedVideo.objects.filter(user=request.user).order_by('-created_at')
        serializer = StitchedVideoSerializer(videos, many=True)
        return Response(serializer.data)

class StitchedVideoDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        sv = get_object_or_404(StitchedVideo, pk=pk, user=request.user)
        serializer = StitchedVideoSerializer(sv)
        return Response(serializer.data)
    
    def delete(self, request, pk):
        sv = get_object_or_404(StitchedVideo, pk=pk, user=request.user)
        sv.delete() # Signals handle file deletion
        return Response(status=status.HTTP_204_NO_CONTENT)





# ── Prompt Enhancement ────────────────────────────────────────────────────────

class PromptEnhanceView(APIView):
    """
    POST /api/enhance-prompt/
    Body: { "prompt": "raw user text" }
    Returns: { "enhanced_prompt": "structured prompt" }

    Uses ChromaDB RAG + Groq (primary) / Gemini (fallback) to rephrase
    the user's raw idea into the wording style of the Manimatic dataset.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_prompt = request.data.get("prompt", "").strip()
        if not raw_prompt:
            return Response(
                {"error": "Prompt is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(raw_prompt) > 2000:
            return Response(
                {"error": "Prompt too long. Please keep it under 2000 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            enhanced = enhance_prompt(raw_prompt)
            return Response({"enhanced_prompt": enhanced})
        except RuntimeError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.error(f"Prompt enhancement unexpected error: {e}")
            return Response(
                {"error": "An unexpected error occurred during prompt enhancement."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

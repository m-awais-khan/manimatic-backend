from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authtoken.models import Token
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.conf import settings as django_settings
from .models import Scene, Chat, StitchedVideo, UserProfile, DataTrainingOptOut, PlaygroundProject, Project, VideoEditorProject
from .serializers import SceneSerializer, ChatSerializer, StitchedVideoSerializer, PlaygroundProjectSerializer, ProjectSerializer, VideoEditorProjectSerializer
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
from .services.playground.layout_pass import apply_layout_pass
from .services.playground.manifest_validator import validate_manifest
from .services.playground.python_compiler import compile_manifest_to_python
from .services.playground.render_task import compile_and_render_task


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
    Body: { "dataset_id": "0016-bubblesortanimation", "project_id": "uuid" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile

        dataset_id = request.data.get('dataset_id', '').strip()
        project_id = request.data.get('project_id')

        if not dataset_id:
            return Response({'error': '"dataset_id" is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not project_id:
            return Response({'error': '"project_id" is required'}, status=status.HTTP_400_BAD_REQUEST)

        project = get_object_or_404(Project, id=project_id, user=request.user)

        dataset = _load_dataset()
        entry = next((e for e in dataset if e.get('id') == dataset_id), None)
        if entry is None:
            return Response({'error': f'Dataset entry "{dataset_id}" not found'}, status=status.HTTP_404_NOT_FOUND)

        instruction = entry['instruction']
        code = entry.get('output', '')
        dataset_video_path = entry['video_path']

        title = (instruction[:57] + '...') if len(instruction) > 60 else instruction
        chat = Chat.objects.create(title=title, user=request.user, project=project)

        scene = Scene.objects.create(
            chat=chat,
            prompt=instruction,
            code=code,
            video_path=None,
            status='completed',
            target_model='dataset',
        )

        video_filename = dataset_video_path.lstrip('/').split('/')[-1]
        src_path = Path(django_settings.BASE_DIR).parent / 'frontend' / 'public' / 'dataset-videos' / video_filename
        storage_key = f'videos/scene_{scene.id}.mp4'

        try:
            with open(src_path, 'rb') as f:
                saved_name = default_storage.save(storage_key, ContentFile(f.read()))
            stored_video_path = default_storage.url(saved_name)
            scene.video_path = stored_video_path
            scene.save(update_fields=['video_path'])
        except Exception as e:
            logger.error('Failed to copy dataset video: %s', e)
            scene.video_path = dataset_video_path
            scene.save(update_fields=['video_path'])

        return Response({'scene': SceneSerializer(scene).data, 'chat_id': str(chat.id)}, status=status.HTTP_201_CREATED)



# ── Project Views ───────────────────────────────────────────

class ProjectListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        projects = Project.objects.filter(user=request.user).order_by('-updated_at')
        serializer = ProjectSerializer(projects, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = ProjectSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        serializer = ProjectSerializer(project)
        return Response(serializer.data)

    def put(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        serializer = ProjectSerializer(project, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        project = get_object_or_404(Project, pk=pk, user=request.user)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Auth Views ──────────────────────────────────────────────

def _delete_storage_file(video_path):
    from django.core.files.storage import default_storage
    from django.conf import settings as dj_settings

    if not video_path:
        return

    try:
        bucket = getattr(dj_settings, 'AWS_STORAGE_BUCKET_NAME', '')
        if video_path.startswith('http://') or video_path.startswith('https://'):
            marker = f'/object/public/{bucket}/'
            storage_key = video_path.split(marker, 1)[1] if marker in video_path else video_path.split('/')[-1]
        else:
            storage_key = video_path.lstrip('/').removeprefix('media/').lstrip('/')
        default_storage.delete(storage_key)
    except Exception as e:
        logger.warning(f"Could not delete storage file '{video_path}': {e}")


class GoogleAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get('id_token')
        if not id_token:
            return Response({'error': 'id_token is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            resp = requests.get(f'https://oauth2.googleapis.com/tokeninfo?id_token={id_token}', timeout=10)
            if resp.status_code != 200:
                return Response({'error': 'Invalid token'}, status=status.HTTP_401_UNAUTHORIZED)
            google_data = resp.json()
            if google_data.get('aud') != django_settings.GOOGLE_CLIENT_ID:
                return Response({'error': 'Token audience mismatch'}, status=status.HTTP_401_UNAUTHORIZED)
            google_id, email = google_data.get('sub'), google_data.get('email', '')
            name, picture = google_data.get('name', email.split('@')[0]), google_data.get('picture', '')
        except Exception as e:
            return Response({'error': f'Token verification failed: {str(e)}'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            profile = UserProfile.objects.get(google_id=google_id)
            user = profile.user
            profile.display_name, profile.profile_picture = name, picture
            profile.save()
        except UserProfile.DoesNotExist:
            user = User.objects.create_user(username=f'google_{google_id}', email=email)
            profile = UserProfile.objects.create(user=user, google_id=google_id, display_name=name, profile_picture=picture)

        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'profile': {'email': user.email, 'display_name': profile.display_name, 'profile_picture': profile.profile_picture}
        })


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        return Response({'email': request.user.email, 'display_name': profile.display_name, 'profile_picture': profile.profile_picture})

    def delete(self, request):
        request.user.delete()
        return Response({'message': 'Account deleted'}, status=status.HTTP_204_NO_CONTENT)


class DataTrainingConsentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        opted_out = DataTrainingOptOut.objects.filter(user=request.user).exists()
        return Response({'consented': not opted_out})

    def post(self, request):
        consented = request.data.get('consented')
        if consented is None:
            return Response({'error': '"consented" field is required'}, status=status.HTTP_400_BAD_REQUEST)
        if consented:
            DataTrainingOptOut.objects.filter(user=request.user).delete()
        else:
            DataTrainingOptOut.objects.get_or_create(user=request.user)
        return Response({'consented': bool(consented)})


class WipeDataView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        Project.objects.filter(user=request.user).delete()
        Chat.objects.filter(user=request.user).delete()
        PlaygroundProject.objects.filter(user=request.user).delete()
        VideoEditorProject.objects.filter(user=request.user).delete()
        StitchedVideo.objects.filter(user=request.user).delete()
        return Response({'message': 'All data wiped'}, status=status.HTTP_204_NO_CONTENT)


# ── Chat Views (project-scoped) ───────────────────────────────

class ChatListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project_id = request.query_params.get('project_id')
        if not project_id:
            return Response({'error': 'project_id required'}, status=status.HTTP_400_BAD_REQUEST)
        chats = Chat.objects.filter(user=request.user, project_id=project_id).order_by('-updated_at')
        return Response(ChatSerializer(chats, many=True).data)

class ChatDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk, user=request.user)
        return Response(ChatSerializer(chat).data)
        
    def delete(self, request, pk):
        get_object_or_404(Chat, pk=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class GenerateSceneView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        chat_id = request.data.get('chat_id')
        project_id = request.data.get('project_id')
        prompt = request.data.get('prompt', '')
        
        if chat_id:
            chat = get_object_or_404(Chat, id=chat_id, user=request.user)
        else:
            if not project_id:
                return Response({'error': 'project_id required to start new chat'}, status=status.HTTP_400_BAD_REQUEST)
            project = get_object_or_404(Project, id=project_id, user=request.user)
            title = prompt[:30] + '...' if len(prompt) > 30 else prompt
            chat = Chat.objects.create(title=title, user=request.user, project=project)

        data = request.data.copy()
        data['chat'] = chat.id

        serializer = SceneSerializer(data=data)
        if serializer.is_valid():
            scene = serializer.save(status='pending', chat=chat)
            quality = request.data.get('quality', '720p')
            threading.Thread(target=generate_scene_task, args=(scene.id, quality)).start()
            return Response({'scene': serializer.data, 'chat_id': chat.id}, status=status.HTTP_202_ACCEPTED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PlaygroundRenderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_manifest = request.data.get('manifest')
        if not isinstance(raw_manifest, dict):
            return Response({'error': '"manifest" is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validated = validate_manifest(raw_manifest).model_dump()
            manifest = apply_layout_pass(validated)
            compiled_python = compile_manifest_to_python(manifest)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        chat_id = request.data.get('chat_id')
        project_id = request.data.get('project_id')
        title = (request.data.get('title') or 'Playground Scene').strip()[:255]
        playground_id = request.data.get('playground_id')
        chat = None
        
        if chat_id:
            chat = get_object_or_404(Chat, id=chat_id, user=request.user)
        else:
            if playground_id:
                try:
                    pg = PlaygroundProject.objects.get(id=playground_id, user=request.user)
                    if pg.last_scene and pg.last_scene.chat:
                        chat = pg.last_scene.chat
                except PlaygroundProject.DoesNotExist:
                    pass

        if not chat:
            if not project_id:
                return Response({'error': 'project_id required'}, status=status.HTTP_400_BAD_REQUEST)
            project = get_object_or_404(Project, id=project_id, user=request.user)
            chat = Chat.objects.create(title=title[:60] or 'Playground Scene', user=request.user, project=project)

        scene = Scene.objects.create(chat=chat, prompt=title, code=compiled_python, manifest=manifest, source='playground', target_model='deterministic-playground', status='pending')

        playground_id = request.data.get('playground_id')
        if playground_id:
            pg = get_object_or_404(PlaygroundProject, id=playground_id, user=request.user)
            pg.manifest, pg.compiled_python, pg.last_scene = manifest, compiled_python, scene
            pg.save()

        quality = request.data.get('quality', '720p')
        threading.Thread(target=compile_and_render_task, args=(scene.id, quality)).start()
        return Response({'scene': SceneSerializer(scene).data, 'chat_id': str(chat.id), 'compiled_python': compiled_python, 'manifest': manifest}, status=status.HTTP_202_ACCEPTED)


class PlaygroundProjectListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project_id = request.query_params.get('project_id')
        if not project_id:
            return Response({'error': 'project_id required'}, status=status.HTTP_400_BAD_REQUEST)
        sessions = PlaygroundProject.objects.filter(user=request.user, project_id=project_id)
        return Response(PlaygroundProjectSerializer(sessions, many=True).data)

    def post(self, request):
        project_id = request.data.get('project_id')
        if not project_id:
            return Response({'error': 'project_id required'}, status=status.HTTP_400_BAD_REQUEST)
        project = get_object_or_404(Project, id=project_id, user=request.user)
        
        title = (request.data.get('title') or 'Untitled Playground').strip()[:255]
        pg = PlaygroundProject.objects.create(user=request.user, project=project, title=title, graph_data=request.data.get('graph_data', {}))
        return Response(PlaygroundProjectSerializer(pg).data, status=status.HTTP_201_CREATED)


class PlaygroundProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        pg = get_object_or_404(PlaygroundProject, pk=pk, user=request.user)
        return Response(PlaygroundProjectSerializer(pg).data)

    def put(self, request, pk):
        pg = get_object_or_404(PlaygroundProject, pk=pk, user=request.user)
        pg.title = (request.data.get('title') or pg.title).strip()[:255]
        pg.graph_data = request.data.get('graph_data', pg.graph_data)
        pg.save()
        return Response(PlaygroundProjectSerializer(pg).data)

    def delete(self, request, pk):
        get_object_or_404(PlaygroundProject, pk=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class VideoEditorProjectListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project_id = request.query_params.get('project_id')
        if not project_id:
            return Response({'error': 'project_id required'}, status=status.HTTP_400_BAD_REQUEST)
        projects = VideoEditorProject.objects.filter(user=request.user, project_id=project_id)
        return Response(VideoEditorProjectSerializer(projects, many=True).data)

    def post(self, request):
        project_id = request.data.get('project_id')
        if not project_id:
            return Response({'error': 'project_id required'}, status=status.HTTP_400_BAD_REQUEST)
        project = get_object_or_404(Project, id=project_id, user=request.user)
        title = (request.data.get('title') or 'Untitled Edit').strip()[:255]
        edit_data = request.data.get('edit_data', {})
        if not isinstance(edit_data, dict):
            return Response({'error': 'edit_data must be an object'}, status=status.HTTP_400_BAD_REQUEST)
        editor_project = VideoEditorProject.objects.create(user=request.user, project=project, title=title, edit_data=edit_data)
        return Response(VideoEditorProjectSerializer(editor_project).data, status=status.HTTP_201_CREATED)

class VideoEditorProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        editor_project = get_object_or_404(VideoEditorProject, pk=pk, user=request.user)
        return Response(VideoEditorProjectSerializer(editor_project).data)

    def put(self, request, pk):
        editor_project = get_object_or_404(VideoEditorProject, pk=pk, user=request.user)
        editor_project.title = (request.data.get('title') or editor_project.title).strip()[:255]
        edit_data = request.data.get('edit_data', editor_project.edit_data)
        if not isinstance(edit_data, dict):
            return Response({'error': 'edit_data must be an object'}, status=status.HTTP_400_BAD_REQUEST)
        editor_project.edit_data = edit_data
        editor_project.save()
        return Response(VideoEditorProjectSerializer(editor_project).data)

    def delete(self, request, pk):
        get_object_or_404(VideoEditorProject, pk=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class SceneStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        scene = get_object_or_404(Scene, pk=pk)
        return Response(SceneSerializer(scene).data)

class StitchVideosView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        project_id = request.data.get('project_id')
        if not project_id:
            return Response({'error': 'project_id required'}, status=status.HTTP_400_BAD_REQUEST)
        project = get_object_or_404(Project, id=project_id, user=request.user)
        
        raw_clips = request.data.get('clips')
        video_paths = request.data.get('video_paths', [])
        title = request.data.get('title', 'Stitched Video')
        if isinstance(raw_clips, list) and raw_clips:
            video_paths = [clip.get('video_path') for clip in raw_clips if clip.get('video_path')]
        if not video_paths or len(video_paths) < 2:
            return Response({'error': 'Need 2+ videos.'}, status=status.HTTP_400_BAD_REQUEST)
        
        edit_plan = None
        if isinstance(raw_clips, list):
            edit_plan = {
                'clips': raw_clips,
                'transitions': request.data.get('transitions', []),
                'output': request.data.get('output', {}),
            }

        sv = StitchedVideo.objects.create(title=title, source_video_paths=video_paths, status='pending', user=request.user, project=project)
        threading.Thread(target=stitch_videos_task, args=(sv.id, request.data.get('transition', 'cut'), edit_plan)).start()
        return Response(StitchedVideoSerializer(sv).data, status=status.HTTP_202_ACCEPTED)

class StitchedVideoListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        project_id = request.query_params.get('project_id')
        if not project_id:
            return Response({'error': 'project_id required'}, status=status.HTTP_400_BAD_REQUEST)
        videos = StitchedVideo.objects.filter(user=request.user, project_id=project_id).order_by('-created_at')
        return Response(StitchedVideoSerializer(videos, many=True).data)

class StitchedVideoDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        sv = get_object_or_404(StitchedVideo, pk=pk, user=request.user)
        return Response(StitchedVideoSerializer(sv).data)
    
    def delete(self, request, pk):
        get_object_or_404(StitchedVideo, pk=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class PromptEnhanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_prompt = request.data.get("prompt", "").strip()
        if not raw_prompt:
            return Response({"error": "Prompt is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            enhanced = enhance_prompt(raw_prompt)
            return Response({"enhanced_prompt": enhanced})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

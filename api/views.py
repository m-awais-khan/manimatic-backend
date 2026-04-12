from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authtoken.models import Token
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.conf import settings as django_settings
from .models import Scene, Chat, StitchedVideo, UserProfile
from .serializers import SceneSerializer, ChatSerializer, StitchedVideoSerializer
import threading
import requests
import os
import shutil
from .services.generator import generate_scene_task
from .services.stitcher import stitch_videos_task

# ── Auth Views ──────────────────────────────────────────────

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
        """Delete account and ALL associated data."""
        user = request.user
        # Delete all user media files
        for chat in Chat.objects.filter(user=user):
            for scene in chat.scenes.all():
                if scene.video_path:
                    try:
                        full_path = os.path.join(django_settings.BASE_DIR, scene.video_path.lstrip('/'))
                        if os.path.exists(full_path):
                            os.remove(full_path)
                    except: pass
        for sv in StitchedVideo.objects.filter(user=user):
            if sv.video_path:
                try:
                    full_path = os.path.join(django_settings.BASE_DIR, sv.video_path.lstrip('/'))
                    if os.path.exists(full_path):
                        os.remove(full_path)
                except: pass

        user.delete()  # Cascades to Profile, Chats, Scenes, StitchedVideos
        return Response({'message': 'Account deleted'}, status=status.HTTP_204_NO_CONTENT)


class WipeDataView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        """Wipe all user data but keep the account."""
        user = request.user
        # Delete chats (cascades to scenes)
        for chat in Chat.objects.filter(user=user):
            for scene in chat.scenes.all():
                if scene.video_path:
                    try:
                        full_path = os.path.join(django_settings.BASE_DIR, scene.video_path.lstrip('/'))
                        if os.path.exists(full_path):
                            os.remove(full_path)
                    except: pass
            chat.delete()

        # Delete stitched videos
        for sv in StitchedVideo.objects.filter(user=user):
            if sv.video_path:
                try:
                    full_path = os.path.join(django_settings.BASE_DIR, sv.video_path.lstrip('/'))
                    if os.path.exists(full_path):
                        os.remove(full_path)
                except: pass
            sv.delete()

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
        chat.delete()
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
        sv.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

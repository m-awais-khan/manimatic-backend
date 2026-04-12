from rest_framework import serializers
from .models import Scene, Chat, StitchedVideo, UserProfile

class SceneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scene
        fields = '__all__'
        read_only_fields = ('id', 'status', 'code', 'video_path', 'error_message', 'created_at', 'updated_at')

class ChatSerializer(serializers.ModelSerializer):
    scenes = SceneSerializer(many=True, read_only=True)

    class Meta:
        model = Chat
        fields = ['id', 'title', 'created_at', 'updated_at', 'scenes']

class StitchedVideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = StitchedVideo
        fields = ['id', 'title', 'video_path', 'source_video_paths', 'status', 'error_message', 'created_at']
        read_only_fields = ('id', 'video_path', 'status', 'error_message', 'created_at')

class UserProfileSerializer(serializers.Serializer):
    email = serializers.EmailField()
    display_name = serializers.CharField()
    profile_picture = serializers.URLField(allow_blank=True)

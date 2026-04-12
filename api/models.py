from django.db import models
from django.contrib.auth.models import User
import uuid

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    google_id = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    profile_picture = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.display_name} ({self.user.email})"

class Chat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chats', null=True, blank=True)
    title = models.CharField(max_length=255, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

class Scene(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(Chat, related_name='scenes', on_delete=models.CASCADE, null=True, blank=True)
    prompt = models.TextField()
    text_response = models.TextField(blank=True, null=True)
    reference_image = models.ImageField(upload_to='scene_references/', null=True, blank=True)
    target_model = models.CharField(max_length=50, default='gemini-2.5-flash')
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('generating_code', 'Generating Code'),
            ('rendering', 'Rendering Animation'),
            ('completed', 'Completed'),
            ('error', 'Error'),
        ],
        default='pending'
    )
    
    code = models.TextField(blank=True, null=True)
    video_path = models.CharField(max_length=500, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Scene {self.id} - {self.status}"

class StitchedVideo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='stitched_videos', null=True, blank=True)
    title = models.CharField(max_length=255, default="Stitched Video")
    video_path = models.CharField(max_length=500, blank=True, null=True)
    source_video_paths = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('error', 'Error'),
        ],
        default='pending'
    )
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Stitched {self.id} - {self.status}"

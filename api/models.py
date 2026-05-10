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

class DataTrainingOptOut(models.Model):
    """
    Records users who have opted OUT of allowing their data
    to be used for training Manimatic's custom AI model.

    By default every user is opted IN (consented).  A row is created
    here only when the user explicitly disables the toggle in Settings.
    Deleting a row restores the user to the opted-in (consented) state.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='training_opt_out'
    )
    opted_out_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Data Training Opt-Out'
        verbose_name_plural = 'Data Training Opt-Outs'

    def __str__(self):
        return f"{self.user.email} — opted out at {self.opted_out_at:%Y-%m-%d %H:%M UTC}"

class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    title = models.CharField(max_length=255, default="Untitled Project")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

class Chat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chats', null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='chats', null=True, blank=True)
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
    source = models.CharField(
        max_length=20,
        choices=[
            ('chat', 'Chat'),
            ('dataset', 'Dataset'),
            ('playground', 'Playground'),
        ],
        default='chat'
    )
    manifest = models.JSONField(null=True, blank=True)
    
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

class PlaygroundProject(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='playground_projects')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='playground_projects', null=True, blank=True)
    title = models.CharField(max_length=255, default='Untitled Playground')
    graph_data = models.JSONField(default=dict, blank=True)
    manifest = models.JSONField(null=True, blank=True)
    compiled_python = models.TextField(blank=True, null=True)
    last_scene = models.ForeignKey(
        Scene,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='playground_projects'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

class StitchedVideo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='stitched_videos', null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='stitched_videos', null=True, blank=True)
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

from django.db.models.signals import post_delete
from django.dispatch import receiver

@receiver(post_delete, sender=Scene)
def delete_scene_files(sender, instance, **kwargs):
    """Automatically delete the associated video and reference image when a Scene is deleted."""
    from api.views import _delete_storage_file
    if instance.video_path:
        _delete_storage_file(instance.video_path)
    if instance.reference_image:
        instance.reference_image.delete(save=False)

@receiver(post_delete, sender=StitchedVideo)
def delete_stitched_video_files(sender, instance, **kwargs):
    """Automatically delete the associated video when a StitchedVideo is deleted."""
    from api.views import _delete_storage_file
    if instance.video_path:
        _delete_storage_file(instance.video_path)

from django.contrib import admin
from .models import Scene

@admin.register(Scene)
class SceneAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('prompt',)

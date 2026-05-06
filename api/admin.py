from django.contrib import admin
from .models import Scene, DataTrainingOptOut

@admin.register(Scene)
class SceneAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('prompt',)

@admin.register(DataTrainingOptOut)
class DataTrainingOptOutAdmin(admin.ModelAdmin):
    list_display = ('user_email', 'opted_out_at')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('user', 'opted_out_at')

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User Email'
    user_email.admin_order_field = 'user__email'

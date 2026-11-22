from django.contrib import admin

from .models import Scene, VideoProject


class SceneInline(admin.TabularInline):
    model = Scene
    extra = 0
    fields = ("index", "status", "duration", "job_id", "cost", "error")
    readonly_fields = fields


@admin.register(VideoProject)
class VideoProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "mode", "model", "status", "cost_total", "created_at")
    list_filter = ("mode", "status", "model")
    search_fields = ("title", "idea", "user__username")
    inlines = [SceneInline]

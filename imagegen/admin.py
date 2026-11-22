from django.contrib import admin

from .models import GeneratedImage, Generation, ImageSession, ReferenceImage


class GenerationInline(admin.TabularInline):
    model = Generation
    extra = 0
    fields = ("prompt", "model", "status", "cost", "created_at")
    readonly_fields = fields


@admin.register(ImageSession)
class ImageSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "model", "updated_at")
    search_fields = ("title", "user__username")
    inlines = [GenerationInline]


@admin.register(Generation)
class GenerationAdmin(admin.ModelAdmin):
    list_display = ("prompt", "model", "status", "cost", "created_at")
    list_filter = ("status", "model")


admin.site.register(GeneratedImage)
admin.site.register(ReferenceImage)

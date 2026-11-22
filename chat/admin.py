from django.contrib import admin

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("role", "content", "model", "prompt_tokens", "completion_tokens", "created_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "model", "updated_at")
    list_filter = ("model",)
    search_fields = ("title", "user__username")
    inlines = [MessageInline]

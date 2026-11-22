from django.contrib import admin

from .models import RagChat, RagDocument, RagMessage


@admin.register(RagDocument)
class RagDocumentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "chat", "status", "n_chunks", "embed_model", "created_at")


admin.site.register(RagChat)
admin.site.register(RagMessage)

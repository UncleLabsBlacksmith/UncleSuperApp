import uuid

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


def upload_to(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"rag/{instance.chat.user_id}/{instance.chat_id}/{uuid.uuid4().hex}.{ext}"


class RagChat(models.Model):
    """1 แชท = 1 คลังเอกสาร (อัปโหลดได้หลายไฟล์)"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rag_chats")
    title = models.CharField(max_length=200, default="คลังเอกสารใหม่")
    model = models.CharField(max_length=200, blank=True, default="")
    embed_model = models.CharField(max_length=200, blank=True, default="")
    top_k = models.PositiveSmallIntegerField(default=6)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class RagDocument(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "กำลังประมวลผล"
        READY = "ready", "พร้อมใช้"
        ERROR = "error", "ผิดพลาด"

    chat = models.ForeignKey(RagChat, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to=upload_to)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    progress = models.PositiveSmallIntegerField(default=0)  # %
    error = models.TextField(blank=True, default="")
    warnings = models.JSONField(default=list, blank=True)
    pages = models.PositiveIntegerField(default=0)
    n_chunks = models.PositiveIntegerField(default=0)
    n_chars = models.PositiveIntegerField(default=0)
    embed_model = models.CharField(max_length=200, blank=True, default="")  # ว่าง = ค้นด้วยคำ (keyword) อย่างเดียว
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.original_name


class RagChunk(models.Model):
    document = models.ForeignKey(RagDocument, on_delete=models.CASCADE, related_name="chunks")
    chat = models.ForeignKey(RagChat, on_delete=models.CASCADE, related_name="chunks")
    idx = models.PositiveIntegerField()
    text = models.TextField()
    loc = models.CharField(max_length=120, blank=True, default="")
    embedding = models.BinaryField(null=True, blank=True)  # float32 (normalized) จาก array('f').tobytes()

    class Meta:
        ordering = ["document_id", "idx"]
        indexes = [models.Index(fields=["chat", "document"])]


class RagMessage(models.Model):
    chat = models.ForeignKey(RagChat, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20)
    content = models.TextField(blank=True, default="")
    sources = models.JSONField(default=list, blank=True)
    model = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


@receiver(post_delete, sender=RagDocument)
def _cleanup(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)

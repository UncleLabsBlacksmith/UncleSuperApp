import uuid

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


def upload_to(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"analyst/{instance.session.user_id}/{instance.session_id}/{uuid.uuid4().hex}.{ext}"


class AnalysisSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="analysis_sessions")
    title = models.CharField(max_length=200, default="การวิเคราะห์ใหม่")
    model = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class AnalysisFile(models.Model):
    class Kind(models.TextChoices):
        TABLE = "table", "ตารางข้อมูล"
        TEXT = "text", "เอกสาร"
        IMAGE = "image", "รูปภาพ"

    session = models.ForeignKey(AnalysisSession, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to=upload_to)
    cache = models.FileField(upload_to=upload_to, blank=True)  # ตาราง (JSON) หรือข้อความที่แยกแล้ว
    original_name = models.CharField(max_length=255)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    media_type = models.CharField(max_length=50, blank=True, default="")
    size = models.PositiveBigIntegerField(default=0)
    meta = models.JSONField(default=dict, blank=True)  # sheets / columns / rows / pages / chars / warnings
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.original_name


class AnalysisMessage(models.Model):
    session = models.ForeignKey(AnalysisSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20)  # user / assistant
    content = models.TextField(blank=True, default="")
    charts = models.JSONField(default=list, blank=True)
    metrics = models.JSONField(default=list, blank=True)
    tables = models.JSONField(default=list, blank=True)
    model = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


@receiver(post_delete, sender=AnalysisFile)
def _cleanup(sender, instance, **kwargs):
    for f in (instance.file, instance.cache):
        if f:
            f.delete(save=False)

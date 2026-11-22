import uuid

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

EXT_BY_MEDIA_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/svg+xml": "svg",
}


def _path(instance, filename, kind):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    user_id = instance.generation.session.user_id
    return f"imagegen/{user_id}/{kind}/{uuid.uuid4().hex}.{ext}"


def output_upload_to(instance, filename):
    return _path(instance, filename, "out")


def reference_upload_to(instance, filename):
    return _path(instance, filename, "ref")


class ImageSession(models.Model):
    """ประวัติการสร้างภาพ 1 เธรด (คล้ายห้องแชท)"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="image_sessions")
    title = models.CharField(max_length=200, default="ภาพใหม่")
    model = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class Generation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "กำลังสร้าง"
        SUCCESS = "success", "สำเร็จ"
        ERROR = "error", "ผิดพลาด"

    session = models.ForeignKey(ImageSession, on_delete=models.CASCADE, related_name="generations")
    prompt = models.TextField()
    model = models.CharField(max_length=200)
    params = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True, default="")
    cost = models.FloatField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.model}: {self.prompt[:40]}"


class GeneratedImage(models.Model):
    generation = models.ForeignKey(Generation, on_delete=models.CASCADE, related_name="images")
    file = models.FileField(upload_to=output_upload_to)
    media_type = models.CharField(max_length=50, default="image/png")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def user_id(self):
        return self.generation.session.user_id


class ReferenceImage(models.Model):
    generation = models.ForeignKey(Generation, on_delete=models.CASCADE, related_name="references")
    file = models.FileField(upload_to=reference_upload_to)
    media_type = models.CharField(max_length=50, default="image/png")
    original_name = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["id"]


@receiver(post_delete, sender=GeneratedImage)
@receiver(post_delete, sender=ReferenceImage)
def _delete_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)

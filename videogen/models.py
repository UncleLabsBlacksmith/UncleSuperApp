from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


def project_upload_to(instance, filename):
    project = instance if isinstance(instance, VideoProject) else instance.project
    return f"videogen/{project.user_id}/{project.pk}/{filename}"


class VideoProject(models.Model):
    class Mode(models.TextChoices):
        SINGLE = "single", "Single Video"
        SERIES = "series", "Series Video"

    class Status(models.TextChoices):
        QUEUED = "queued", "รอคิว"
        RUNNING = "running", "กำลังสร้างวิดีโอ"
        MUSIC = "music", "กำลังสร้างเพลงประกอบ"
        STITCHING = "stitching", "กำลังรวมคลิป"
        COMPLETED = "completed", "เสร็จแล้ว"
        PARTIAL = "partial", "เสร็จบางส่วน"
        FAILED = "failed", "ล้มเหลว"
        CANCELLED = "cancelled", "ยกเลิกแล้ว"

    ACTIVE = (Status.QUEUED, Status.RUNNING, Status.MUSIC, Status.STITCHING)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="video_projects")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.SINGLE)
    title = models.CharField(max_length=200, default="วิดีโอใหม่")
    idea = models.TextField(blank=True, default="")
    model = models.CharField(max_length=200)
    config = models.JSONField(default=dict, blank=True)
    style_guide = models.TextField(blank=True, default="")
    music_prompt = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    error = models.TextField(blank=True, default="")
    final_file = models.FileField(upload_to=project_upload_to, blank=True)
    music_file = models.FileField(upload_to=project_upload_to, blank=True)
    first_frame = models.FileField(upload_to=project_upload_to, blank=True)
    cost_total = models.FloatField(default=0)
    seen = models.BooleanField(default=False)  # ผู้ใช้เปิดดูผลลัพธ์แล้วหรือยัง
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_active(self):
        return self.status in self.ACTIVE

    @property
    def total_duration(self):
        return sum(s.duration for s in self.scenes.all())


class Scene(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "รอส่ง"
        SUBMITTED = "submitted", "ส่งแล้ว"
        IN_PROGRESS = "in_progress", "กำลังสร้าง"
        DOWNLOADING = "downloading", "กำลังดาวน์โหลด"
        COMPLETED = "completed", "เสร็จ"
        FAILED = "failed", "ล้มเหลว"
        CANCELLED = "cancelled", "ยกเลิก"

    project = models.ForeignKey(VideoProject, on_delete=models.CASCADE, related_name="scenes")
    index = models.PositiveIntegerField()
    version = models.PositiveIntegerField(default=1)
    prompt = models.TextField()
    prompt_th = models.TextField(blank=True, default="")  # คำแปลไทยของ prompt (แสดงเมื่อชี้ที่ไอคอน)
    narration = models.TextField(blank=True, default="")
    final_prompt = models.TextField(blank=True, default="")  # prompt ที่ส่งจริง (รวมคำสั่งเสียง/สไตล์)
    duration = models.PositiveIntegerField(default=5)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    job_id = models.CharField(max_length=200, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    file = models.FileField(upload_to=project_upload_to, blank=True)
    cost = models.FloatField(null=True, blank=True)
    next_poll_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["index"]
        unique_together = [("project", "index")]

    def __str__(self):
        return f"{self.project_id}#{self.index}"


class SceneVersion(models.Model):
    """เวอร์ชันเก่าของฉาก — เก็บไว้เมื่อผู้ใช้แก้ prompt แล้วสร้างฉากใหม่ (กดกลับไปใช้ได้)"""

    scene = models.ForeignKey(Scene, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    prompt = models.TextField()
    prompt_th = models.TextField(blank=True, default="")
    narration = models.TextField(blank=True, default="")
    final_prompt = models.TextField(blank=True, default="")
    file = models.FileField(upload_to=project_upload_to, blank=True)
    cost = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField()  # เวลาที่คลิปเวอร์ชันนี้ถูกสร้าง
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]

    @property
    def project(self):
        return self.scene.project


class PostCaption(models.Model):
    """ประวัติ "คำอธิบายสำหรับโพสต์" (ชื่อคลิป + description + แฮชแท็ก)
    project = None คือที่สร้างจากหน้าสร้างวิดีโอ (ยังไม่มีงาน)"""

    class Lang(models.TextChoices):
        TH = "th", "ไทย"
        EN = "en", "English"
        BOTH = "both", "ไทย + English"

    class Source(models.TextChoices):
        AI = "ai", "AI เขียน"
        EDITED = "edited", "แก้ไขเอง"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_captions")
    project = models.ForeignKey(VideoProject, on_delete=models.CASCADE, null=True, blank=True, related_name="captions")
    lang = models.CharField(max_length=8, choices=Lang.choices, default=Lang.TH)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.AI)
    title = models.CharField(max_length=200, blank=True, default="")
    description = models.TextField(blank=True, default="")
    hashtags = models.JSONField(default=list, blank=True)
    idea = models.TextField(blank=True, default="")  # ไอเดียตอนสร้าง (ใช้แสดงในประวัติของหน้าสร้าง)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def as_dict(self) -> dict:
        from django.utils import timezone
        return {
            "id": self.pk, "lang": self.lang, "source": self.source, "title": self.title,
            "description": self.description, "hashtags": list(self.hashtags or []), "idea": self.idea[:160],
            "created_at": timezone.localtime(self.created_at).strftime("%d/%m/%Y %H:%M"),
        }


@receiver(post_delete, sender=SceneVersion)
@receiver(post_delete, sender=Scene)
def _delete_scene_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


@receiver(post_delete, sender=VideoProject)
def _delete_project_files(sender, instance, **kwargs):
    for f in (instance.final_file, instance.music_file, instance.first_frame):
        if f:
            f.delete(save=False)

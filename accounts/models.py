from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from . import crypto


class User(AbstractUser):
    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        PRO = "pro", "Pro"
        ADMIN = "admin", "Admin"

    role = models.CharField("ประเภทผู้ใช้", max_length=20, choices=Role.choices, default=Role.MEMBER)

    def save(self, *args, **kwargs):
        # superuser เป็น admin เสมอ
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    # ---- สิทธิ์ตามประเภทผู้ใช้ ----
    @property
    def permissions(self) -> dict:
        return settings.ROLE_PERMISSIONS.get(self.role, settings.ROLE_PERMISSIONS["member"])

    @property
    def can_use_paid_models(self) -> bool:
        return self.permissions.get("allow_paid_models", False)

    @property
    def can_manage_users(self) -> bool:
        return self.is_superuser or self.permissions.get("can_manage_users", False)

    @property
    def daily_message_limit(self):
        return self.permissions.get("daily_message_limit")

    def messages_sent_today(self) -> int:
        from chat.models import Message

        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        return Message.objects.filter(
            conversation__user=self, role=Message.Role.USER, created_at__gte=start
        ).count()

    @property
    def profile(self) -> "UserSettings":
        obj, _ = UserSettings.objects.get_or_create(user=self)
        return obj


class UserSettings(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="app_settings")
    _api_key = models.TextField("OpenRouter API Key (เข้ารหัส)", blank=True, default="", db_column="api_key")
    default_model = models.CharField("โมเดลเริ่มต้น", max_length=200, blank=True, default="")
    system_prompt = models.TextField("System prompt", blank=True, default="")
    temperature = models.FloatField(default=0.7)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User settings"
        verbose_name_plural = "User settings"

    def __str__(self):
        return f"Settings of {self.user}"

    @property
    def api_key(self) -> str:
        return crypto.decrypt(self._api_key)

    @api_key.setter
    def api_key(self, value: str):
        self._api_key = crypto.encrypt((value or "").strip())

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def masked_api_key(self) -> str:
        key = self.api_key
        if not key:
            return ""
        if len(key) <= 12:
            return "•" * len(key)
        return f"{key[:8]}••••••••{key[-4:]}"

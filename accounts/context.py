def admin_badges(request):
    """จำนวนคำขอรีเซ็ตรหัสผ่านที่รออยู่ — แสดงเป็นตัวเลขที่เมนู "จัดการผู้ใช้" """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.can_manage_users:
        return {}
    from django.utils import timezone

    from .models import PasswordResetLink, PasswordResetRequest

    pending = PasswordResetRequest.objects.filter(status=PasswordResetRequest.Status.PENDING).values_list("user_id", flat=True)
    if not pending:
        return {"reset_pending_count": 0}
    linked = set(PasswordResetLink.objects.filter(used_at__isnull=True, revoked_at__isnull=True,
                                                  expires_at__gt=timezone.now()).values_list("user_id", flat=True))
    # นับเฉพาะคำขอที่แอดมินยังไม่ได้สร้างลิงก์ให้
    return {"reset_pending_count": sum(1 for uid in pending if not uid or uid not in linked)}

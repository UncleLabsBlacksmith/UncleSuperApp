import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from chat import openrouter

from .decorators import manager_required
from .forms import AdminCreateUserForm, ForgotPasswordForm, LoginForm, ProfileForm, RegisterForm, SettingsForm
from .models import PasswordResetLink, PasswordResetRequest, User


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:settings")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for f in form.fields.values():
            f.widget.attrs["class"] = "input"
        return form

    def form_valid(self, form):
        messages.success(self.request, "เปลี่ยนรหัสผ่านเรียบร้อยแล้ว")
        return super().form_valid(form)


def register(request):
    if request.user.is_authenticated:
        return redirect("chat:index")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "สมัครสมาชิกสำเร็จ! ตั้งค่า OpenRouter API Key เพื่อเริ่มแชท")
        return redirect("accounts:settings")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def settings_view(request):
    app_settings = request.user.profile
    if request.method == "POST":
        profile_form = ProfileForm(request.POST, instance=request.user)
        settings_form = SettingsForm(request.POST, instance=app_settings)
        if profile_form.is_valid() and settings_form.is_valid():
            profile_form.save()
            settings_form.save()
            messages.success(request, "บันทึกการตั้งค่าแล้ว")
            return redirect("accounts:settings")
    else:
        profile_form = ProfileForm(instance=request.user)
        settings_form = SettingsForm(instance=app_settings)

    return render(
        request,
        "accounts/settings.html",
        {
            "profile_form": profile_form,
            "settings_form": settings_form,
            "app_settings": app_settings,
            "used_today": request.user.messages_sent_today(),
        },
    )


@login_required
@require_POST
def test_api_key(request):
    """ทดสอบ API Key (ที่พิมพ์มา หรือที่บันทึกไว้) กับ OpenRouter"""
    key = (request.POST.get("api_key") or "").strip() or request.user.profile.api_key
    if not key:
        return JsonResponse({"ok": False, "message": "ยังไม่มี API Key"}, status=400)
    ok, info = openrouter.check_key(key)
    return JsonResponse({"ok": ok, **info}, status=200 if ok else 400)


# ---------------------------------------------------------------------------
# จัดการผู้ใช้ (admin เท่านั้น)
# ---------------------------------------------------------------------------
RESET_LINK_HOURS = getattr(settings, "PASSWORD_RESET_LINK_HOURS", 72)


def _client_ip(request):
    return (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")


def _site_base(request) -> str:
    """ที่อยู่เว็บสำหรับใส่ในลิงก์ — ตั้ง SITE_URL ได้ (เช่น http://192.168.1.20:8000) ไม่งั้นใช้ที่อยู่ที่แอดมินเปิดอยู่"""
    base = getattr(settings, "SITE_URL", "") or request.build_absolute_uri("/")
    return base.rstrip("/")


@manager_required
def user_list(request):
    users = User.objects.annotate(conv_count=Count("conversations", distinct=True)).order_by("-date_joined")
    role_counts = {r: users.filter(role=r).count() for r, _ in User.Role.choices}
    now = timezone.now()
    active_links = {
        l.user_id: l for l in PasswordResetLink.objects.filter(used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now)
    }
    for u in users:
        u.active_link = active_links.get(u.pk)
    requests_qs = list(PasswordResetRequest.objects.select_related("user").filter(status=PasswordResetRequest.Status.PENDING))
    for r in requests_qs:
        r.active_link = active_links.get(r.user_id) if r.user_id else None
    # ลิงก์ที่เพิ่งสร้าง (แสดง token ครั้งเดียว) / รหัสผ่านที่เพิ่งสุ่มให้ผู้ใช้ใหม่
    issued = request.session.pop("issued_reset_link", None)
    created = request.session.pop("created_user", None)
    host = request.get_host().split(":")[0]
    return render(
        request,
        "accounts/users.html",
        {
            "users": users, "roles": User.Role.choices, "role_counts": role_counts,
            "reset_requests": requests_qs, "issued": issued, "created": created,
            "create_form": AdminCreateUserForm(initial={"role": User.Role.MEMBER}),
            "link_hours": RESET_LINK_HOURS,
            "local_host_warning": host in ("127.0.0.1", "localhost", "::1") and not getattr(settings, "SITE_URL", ""),
        },
    )


@manager_required
@require_POST
def user_create(request):
    form = AdminCreateUserForm(request.POST)
    if not form.is_valid():
        errors = "; ".join(f"{form.fields[k].label if k in form.fields else ''}: {' '.join(v)}" for k, v in form.errors.items())
        messages.error(request, f"เพิ่มผู้ใช้ไม่สำเร็จ — {errors}")
        return redirect("accounts:users")
    user = form.save(commit=False)
    password = form.cleaned_data.get("password") or ""
    generated = not password
    if generated:
        password = secrets.token_urlsafe(9)  # 12 ตัวอักษร
    user.set_password(password)
    user.save()
    login_url = _site_base(request) + reverse("accounts:login")
    request.session["created_user"] = {
        "username": user.username, "email": user.email, "password": password if generated else "", "generated": generated,
        "login_url": login_url,
        "message": (f"บัญชี Uncle Super App ของคุณพร้อมใช้งานแล้ว\n\nเข้าสู่ระบบที่: {login_url}\nชื่อผู้ใช้: {user.username}\n"
                    + (f"รหัสผ่านชั่วคราว: {password}\n\nกรุณาเปลี่ยนรหัสผ่านที่เมนู ตั้งค่า → เปลี่ยนรหัสผ่าน หลังเข้าสู่ระบบครั้งแรก" if generated else
                       "รหัสผ่าน: (แจ้งแยกต่างหาก)")),
    }
    messages.success(request, f"เพิ่มผู้ใช้ {user.username} แล้ว")
    return redirect("accounts:users")


@manager_required
@require_POST
def reset_link_create(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.is_superuser and not request.user.is_superuser:
        messages.error(request, "ไม่มีสิทธิ์สร้างลิงก์ให้ superuser")
        return redirect("accounts:users")
    link, token = PasswordResetLink.issue(target, request.user, RESET_LINK_HOURS)
    url = _site_base(request) + reverse("accounts:reset_password", args=[token])
    expires = timezone.localtime(link.expires_at).strftime("%d/%m/%Y %H:%M")
    name = target.get_full_name() or target.username
    request.session["issued_reset_link"] = {
        "user_id": target.pk, "username": target.username, "email": target.email, "url": url, "expires": expires,
        "mail_subject": "ลิงก์ตั้งรหัสผ่านใหม่ - Uncle Super App",
        "mail_body": (
            f"สวัสดีคุณ {name}\n\n"
            f"ตามที่คุณแจ้งลืมรหัสผ่าน Uncle Super App (ชื่อผู้ใช้: {target.username})\n"
            f"กดลิงก์ด้านล่างเพื่อตั้งรหัสผ่านใหม่:\n\n{url}\n\n"
            f"- ลิงก์ใช้ได้ครั้งเดียว และหมดอายุ {expires}\n"
            f"- หากคุณไม่ได้ขอรีเซ็ตรหัสผ่าน กรุณาแจ้งผู้ดูแลระบบ\n\n"
            f"ผู้ดูแลระบบ Uncle Super App"
        ),
    }
    messages.success(request, f"สร้างลิงก์รีเซ็ตรหัสผ่านให้ {target.username} แล้ว — คัดลอกแล้วส่งให้ผู้ใช้")
    return redirect("accounts:users")


@manager_required
@require_POST
def reset_link_revoke(request, pk):
    target = get_object_or_404(User, pk=pk)
    n = PasswordResetLink.objects.filter(user=target, used_at__isnull=True, revoked_at__isnull=True).update(revoked_at=timezone.now())
    messages.success(request, f"ยกเลิกลิงก์รีเซ็ตของ {target.username} แล้ว" if n else "ไม่มีลิงก์ที่ใช้งานได้")
    return redirect("accounts:users")


@manager_required
@require_POST
def reset_request_dismiss(request, pk):
    req = get_object_or_404(PasswordResetRequest, pk=pk)
    req.status, req.resolved_at = PasswordResetRequest.Status.DISMISSED, timezone.now()
    req.save(update_fields=["status", "resolved_at"])
    messages.success(request, "ปิดคำขอแล้ว")
    return redirect("accounts:users")


# ---------------------------------------------------------------------------
# ลืมรหัสผ่าน (ไม่ต้องล็อกอิน)
# ---------------------------------------------------------------------------
def forgot_password(request):
    form = ForgotPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ident = form.cleaned_data["identifier"].strip()
        ip = _client_ip(request)
        hour_ago = timezone.now() - timedelta(hours=1)
        recent = PasswordResetRequest.objects.filter(created_at__gte=hour_ago)
        # กันกดซ้ำ/สแปม: คำขอเดิมที่ยังรออยู่ไม่สร้างซ้ำ และจำกัด 5 ครั้ง/ชั่วโมง/IP
        if not recent.filter(identifier__iexact=ident, status=PasswordResetRequest.Status.PENDING).exists() \
                and recent.filter(ip=ip).count() < 5:
            user = User.objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident)).order_by("-is_active").first() if ident else None
            PasswordResetRequest.objects.create(identifier=ident[:254], user=user, note=form.cleaned_data.get("note", ""), ip=ip)
        # แสดงข้อความเดียวกันเสมอ ไม่บอกว่ามีบัญชีนี้หรือไม่
        return render(request, "accounts/forgot_password_done.html")
    return render(request, "accounts/forgot_password.html", {"form": form})


def reset_password(request, token):
    link = PasswordResetLink.objects.select_related("user").filter(token_hash=PasswordResetLink.hash_token(token)).first()
    if not link or not link.is_valid:
        reason = "ลิงก์นี้ไม่ถูกต้อง"
        if link and link.used_at:
            reason = "ลิงก์นี้ถูกใช้ตั้งรหัสผ่านไปแล้ว"
        elif link and link.revoked_at:
            reason = "ลิงก์นี้ถูกยกเลิกแล้ว (อาจมีลิงก์ใหม่กว่า)"
        elif link and link.expires_at <= timezone.now():
            reason = "ลิงก์นี้หมดอายุแล้ว"
        return render(request, "accounts/reset_password.html", {"invalid": reason}, status=410 if link else 404)
    form = SetPasswordForm(link.user, request.POST or None)
    for f in form.fields.values():
        f.widget.attrs["class"] = "input"
    form.fields["new_password1"].label = "รหัสผ่านใหม่"
    form.fields["new_password2"].label = "ยืนยันรหัสผ่านใหม่"
    if request.method == "POST" and form.is_valid():
        form.save()
        now = timezone.now()
        link.used_at = now
        link.save(update_fields=["used_at"])
        PasswordResetLink.objects.filter(user=link.user, used_at__isnull=True, revoked_at__isnull=True).update(revoked_at=now)
        PasswordResetRequest.objects.filter(user=link.user, status=PasswordResetRequest.Status.PENDING).update(
            status=PasswordResetRequest.Status.DONE, resolved_at=now)
        if request.user.is_authenticated and request.user.pk == link.user.pk:
            update_session_auth_hash(request, link.user)
        messages.success(request, "ตั้งรหัสผ่านใหม่เรียบร้อย — เข้าสู่ระบบด้วยรหัสผ่านใหม่ได้เลย")
        return redirect("accounts:login")
    return render(request, "accounts/reset_password.html", {"form": form, "target": link.user})


@manager_required
@require_POST
def user_update(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "ไม่สามารถแก้ไขสิทธิ์ของตัวเองได้")
        return redirect("accounts:users")
    if target.is_superuser and not request.user.is_superuser:
        messages.error(request, "ไม่มีสิทธิ์แก้ไข superuser")
        return redirect("accounts:users")

    role = request.POST.get("role")
    if role in User.Role.values:
        target.role = role
    if "toggle_active" in request.POST:
        target.is_active = not target.is_active
    target.save()
    messages.success(request, f"อัปเดตผู้ใช้ {target.username} แล้ว")
    return redirect("accounts:users")

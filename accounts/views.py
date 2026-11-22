from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from chat import openrouter

from .decorators import manager_required
from .forms import LoginForm, ProfileForm, RegisterForm, SettingsForm
from .models import User


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
@manager_required
def user_list(request):
    users = User.objects.annotate(conv_count=Count("conversations", distinct=True)).order_by("-date_joined")
    role_counts = {r: users.filter(role=r).count() for r, _ in User.Role.choices}
    return render(
        request,
        "accounts/users.html",
        {"users": users, "roles": User.Role.choices, "role_counts": role_counts},
    )


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

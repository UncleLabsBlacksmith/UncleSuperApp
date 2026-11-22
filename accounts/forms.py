from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User, UserSettings


class StyledMixin:
    def _style(self):
        for name, field in self.fields.items():
            css = "input"
            if isinstance(field.widget, forms.Textarea):
                css = "input textarea"
            elif isinstance(field.widget, forms.Select):
                css = "input select"
            field.widget.attrs.setdefault("class", css)


class LoginForm(StyledMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(placeholder="ชื่อผู้ใช้", autofocus=True)
        self.fields["password"].widget.attrs.update(placeholder="รหัสผ่าน")
        self._style()


class RegisterForm(StyledMixin, UserCreationForm):
    email = forms.EmailField(required=False, label="อีเมล")

    class Meta:
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(placeholder="ชื่อผู้ใช้")
        self.fields["email"].widget.attrs.update(placeholder="you@example.com (ไม่บังคับ)")
        self.fields["password1"].widget.attrs.update(placeholder="อย่างน้อย 8 ตัวอักษร")
        self.fields["password2"].widget.attrs.update(placeholder="พิมพ์รหัสผ่านอีกครั้ง")
        self._style()


class SettingsForm(StyledMixin, forms.ModelForm):
    api_key = forms.CharField(
        label="OpenRouter API Key",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"placeholder": "sk-or-v1-...", "autocomplete": "off"}),
        help_text="เว้นว่างไว้เพื่อใช้คีย์เดิม",
    )
    clear_api_key = forms.BooleanField(label="ลบ API Key ที่บันทึกไว้", required=False)
    temperature = forms.FloatField(min_value=0, max_value=2, widget=forms.NumberInput(attrs={"step": "0.1"}))

    class Meta:
        model = UserSettings
        fields = ("default_model", "system_prompt", "temperature")
        widgets = {
            "default_model": forms.TextInput(attrs={"placeholder": "เช่น meta-llama/llama-3.3-70b-instruct:free"}),
            "system_prompt": forms.Textarea(attrs={"rows": 4, "placeholder": "เช่น ตอบเป็นภาษาไทย กระชับ เข้าใจง่าย"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["clear_api_key"].widget.attrs["class"] = "checkbox"

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("clear_api_key"):
            obj.api_key = ""
        elif self.cleaned_data.get("api_key"):
            obj.api_key = self.cleaned_data["api_key"]
        if commit:
            obj.save()
        return obj


class ProfileForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "ชื่อ", "last_name": "นามสกุล", "email": "อีเมล"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/test-key/", views.test_api_key, name="test_key"),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    path("users/", views.user_list, name="users"),
    path("users/<int:pk>/", views.user_update, name="user_update"),
]

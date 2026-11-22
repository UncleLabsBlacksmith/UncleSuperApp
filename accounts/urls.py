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
    path("users/add/", views.user_create, name="user_create"),
    path("users/<int:pk>/reset-link/", views.reset_link_create, name="reset_link_create"),
    path("users/<int:pk>/reset-link/revoke/", views.reset_link_revoke, name="reset_link_revoke"),
    path("reset-requests/<int:pk>/dismiss/", views.reset_request_dismiss, name="reset_request_dismiss"),
    path("forgot-password/", views.forgot_password, name="forgot_password"),
    path("reset/<str:token>/", views.reset_password, name="reset_password"),
]

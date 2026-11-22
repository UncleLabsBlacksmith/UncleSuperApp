from django.urls import path

from . import views

app_name = "analyst"

urlpatterns = [
    path("", views.index, name="index"),
    path("s/<int:session_id>/", views.index, name="session"),
    path("api/upload/", views.api_upload, name="api_upload"),
    path("api/ask/", views.api_ask, name="api_ask"),
    path("api/files/<int:pk>/delete/", views.api_delete_file, name="api_delete_file"),
    path("api/sessions/<int:pk>/rename/", views.api_rename, name="api_rename"),
    path("api/sessions/<int:pk>/delete/", views.api_delete, name="api_delete"),
]

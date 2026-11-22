from django.urls import path

from . import views

app_name = "videogen"

urlpatterns = [
    path("", views.index, name="index"),
    path("p/<int:pk>/", views.project_detail, name="project"),
    path("file/<str:kind>/<int:pk>/", views.file_view, name="file"),
    path("api/models/", views.api_models, name="api_models"),
    path("api/assist/", views.api_assist, name="api_assist"),
    path("api/create/", views.api_create, name="api_create"),
    path("api/badge/", views.api_badge, name="api_badge"),
    path("api/projects/<int:pk>/", views.api_status, name="api_status"),
    path("api/projects/<int:pk>/cancel/", views.api_cancel, name="api_cancel"),
    path("api/projects/<int:pk>/retry/", views.api_retry, name="api_retry"),
    path("api/projects/<int:pk>/delete/", views.api_delete, name="api_delete"),
    path("api/projects/<int:pk>/rename/", views.api_rename, name="api_rename"),
    path("api/assist-scene/", views.api_assist_scene, name="api_assist_scene"),
    path("api/assist-description/", views.api_assist_description, name="api_assist_description"),
    path("api/translate/", views.api_translate, name="api_translate"),
    path("api/scenes/<int:pk>/regenerate/", views.api_scene_regenerate, name="api_scene_regenerate"),
    path("api/versions/<int:pk>/restore/", views.api_scene_restore, name="api_scene_restore"),
    path("zip/<int:pk>/", views.download_zip, name="zip"),
]

from django.urls import path

from . import views

app_name = "imagegen"

urlpatterns = [
    path("", views.index, name="index"),
    path("s/<int:session_id>/", views.index, name="session"),
    path("gallery/", views.gallery, name="gallery"),
    path("file/<str:kind>/<int:pk>/", views.file_view, name="file"),
    path("api/models/", views.api_models, name="api_models"),
    path("api/generate/", views.api_generate, name="api_generate"),
    path("api/images/<int:pk>/delete/", views.api_delete_image, name="api_delete_image"),
    path("api/sessions/<int:pk>/delete/", views.api_delete_session, name="api_delete_session"),
    path("api/sessions/<int:pk>/rename/", views.api_rename_session, name="api_rename_session"),
]

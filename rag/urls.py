from django.urls import path

from . import views

app_name = "rag"

urlpatterns = [
    path("", views.index, name="index"),
    path("c/<int:chat_id>/", views.index, name="chat"),
    path("api/upload/", views.api_upload, name="api_upload"),
    path("api/ask/", views.api_ask, name="api_ask"),
    path("api/embed-models/", views.api_embed_models, name="api_embed_models"),
    path("api/chats/<int:chat_id>/docs/", views.api_docs, name="api_docs"),
    path("api/chats/<int:chat_id>/settings/", views.api_settings, name="api_settings"),
    path("api/chats/<int:pk>/rename/", views.api_rename, name="api_rename"),
    path("api/chats/<int:pk>/delete/", views.api_delete, name="api_delete"),
    path("api/docs/<int:pk>/delete/", views.api_delete_doc, name="api_delete_doc"),
]

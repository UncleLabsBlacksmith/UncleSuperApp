from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.index, name="index"),
    path("c/<int:conv_id>/", views.index, name="conversation"),
    path("api/models/", views.api_models, name="api_models"),
    path("api/send/", views.api_send, name="api_send"),
    path("api/default-model/", views.api_set_default_model, name="api_default_model"),
    path("api/conversations/<int:conv_id>/rename/", views.api_rename, name="api_rename"),
    path("api/conversations/<int:conv_id>/delete/", views.api_delete, name="api_delete"),
]

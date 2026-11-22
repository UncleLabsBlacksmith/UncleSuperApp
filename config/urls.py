from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="chat:index", permanent=False)),
    path("accounts/", include("accounts.urls")),
    path("chat/", include("chat.urls")),
    path("images/", include("imagegen.urls")),
    path("videos/", include("videogen.urls")),
    path("analyst/", include("analyst.urls")),
    path("rag/", include("rag.urls")),
    path("django-admin/", admin.site.urls),
]

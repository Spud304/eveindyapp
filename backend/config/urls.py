from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import callback_view
from config.api import api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("auth/", include("apps.accounts.urls")),
    # The EVE application shared with the old Flask app is registered with /callback.
    path("callback", callback_view, name="legacy-callback"),
]

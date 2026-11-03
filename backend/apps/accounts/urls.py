from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login", views.login_view, name="login"),
    path("callback", views.callback_view, name="callback"),
    path("logout", views.logout_view, name="logout"),
    path("dev-login", views.dev_login_view, name="dev_login"),
]

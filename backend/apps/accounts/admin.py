from django.contrib import admin

from .models import EsiToken, EveCharacter, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("display_name", "username", "main_character", "is_staff", "created_at")
    search_fields = ("display_name", "username")


@admin.register(EveCharacter)
class EveCharacterAdmin(admin.ModelAdmin):
    list_display = ("name", "character_id", "corporation_id", "user", "last_login_at")
    search_fields = ("name", "character_id")


@admin.register(EsiToken)
class EsiTokenAdmin(admin.ModelAdmin):
    list_display = ("character", "last_refreshed_at", "refresh_failed_at")
    exclude = ("refresh_token", "access_token")  # never shown, even encrypted
    readonly_fields = ("scopes", "access_expires_at", "last_refreshed_at", "refresh_error")

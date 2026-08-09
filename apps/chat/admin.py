from django.contrib import admin

from .models import Conversation, ConversationMember, Message, MessageReaction


class ConversationMemberInline(admin.TabularInline):
    model = ConversationMember
    extra = 0
    readonly_fields = ("user", "unread_count", "last_read_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "match_id", "is_active", "message_count", "last_message_at")
    list_filter = ("is_active",)
    search_fields = ("id", "match_id")
    readonly_fields = ("id", "match_id", "message_count", "created_at", "updated_at")
    inlines = [ConversationMemberInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "conversation", "kind", "short_body",
                    "is_read", "is_flagged", "created_at")
    list_filter = ("kind", "is_read", "is_flagged", "is_deleted")
    search_fields = ("sender__email", "body")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at", "updated_at")

    @admin.display(description="Body")
    def short_body(self, obj):
        return (obj.body[:60] + "…") if len(obj.body) > 60 else obj.body


@admin.register(MessageReaction)
class MessageReactionAdmin(admin.ModelAdmin):
    list_display = ("message", "user", "emoji", "created_at")
    search_fields = ("user__email",)

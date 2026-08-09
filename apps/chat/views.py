"""Server-rendered chat pages.

The view prepares complete conversation rows and message dicts; the template
only loops and prints. Live updates are handled by static/js/chat.js.

Chat is an ordinary section of the app: every page here renders inside the
signed-in shell, in the same window and the same session. There is no popup and
no separate compose flow — opening a conversation is just navigation.
"""
from django.contrib import messages as flash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView, View

from apps.common.exceptions import ZynoraError
from apps.common.mixins import OnboardingRequiredMixin
from apps.common.registry import services

from .services import ConversationService, MessageService


class InboxView(OnboardingRequiredMixin, TemplateView):
    template_name = "chat/inbox.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)

        rows = ConversationService.rows_for_user(user_id)
        context["rows"] = rows
        context["has_conversations"] = bool(rows)
        context["unread_total"] = sum(r["unread_count"] for r in rows)
        # The heading already says there are none — this says what to do next.
        context["empty_message"] = "Open anyone's profile and send the first message."
        return context


class ConversationView(OnboardingRequiredMixin, TemplateView):
    template_name = "chat/conversation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)
        conversation_id = str(self.kwargs["pk"])

        try:
            conversation = ConversationService.get_for_user(conversation_id, user_id)
        except ZynoraError as exc:
            raise Http404 from exc

        other = conversation.members.exclude(user_id=user_id).first()
        if not other:
            raise Http404

        other_id = str(other.user_id)
        ConversationService.mark_read(conversation_id, user_id)
        person = services.accounts.get_user_ref(other_id)

        context.update({
            "conversation_id": conversation_id,
            "person": person,
            # Not "messages": that name belongs to the flash framework's context
            # processor, and shadowing it renders the thread as toast popups.
            "chat_messages": MessageService.history(conversation_id, user_id, limit=60),
            "is_active": conversation.is_active,
            "closed_reason": conversation.close_reason,
            "match_id": str(conversation.match_id) if conversation.match_id else "",
            "is_match": bool(conversation.match_id),
            "is_muted": ConversationService.member(conversation_id, user_id).is_muted,
            # Open to everyone during the free-growth phase — was gated behind
            # the media_messages entitlement; re-add that check when
            # subscriptions come back.
            "can_send_media": True,
            "rows": ConversationService.rows_for_user(user_id, active_id=conversation_id),
            "intro_title": (
                f"You matched with {person['display_name']}"
                if conversation.match_id else
                f"This is the start of your chat with {person['display_name']}"
            ),
            "intro_text": (
                'Say something better than "hey".'
                if conversation.match_id else
                "You haven't matched yet — a message that mentions their profile "
                "works far better than a wave."
            ),
        })
        return context


class StartConversationView(OnboardingRequiredMixin, View):
    """Every "message" button lands here.

    Opening a chat depends on nothing but safety: not yourself, the other
    account is live, and neither of you has blocked the other. Likes, super
    likes and matches are separate features and are never consulted.
    """

    def get(self, request, user_id):
        try:
            conversation_id = services.chat.open_conversation_with(
                str(request.user.id), str(user_id)
            )
        except ZynoraError as exc:
            flash.error(request, exc.message)
            return redirect("chat:inbox")
        return redirect("chat:conversation", pk=conversation_id)


class SendMessageView(LoginRequiredMixin, View):
    """Non-WebSocket fallback (also used for file uploads)."""

    def post(self, request, pk):
        try:
            message = MessageService.send(
                request.user, pk,
                body=request.POST.get("body", ""),
                kind=request.POST.get("kind", "text"),
                attachment=request.FILES.get("attachment"),
                voice_note=request.FILES.get("voice_note"),
                video=request.FILES.get("video"),
                document=request.FILES.get("document"),
                gif_url=request.POST.get("gif_url", ""),
                reply_to_id=request.POST.get("reply_to") or None,
            )
        except ZynoraError as exc:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {"success": False, "code": exc.code, "message": exc.message},
                    status=exc.status_code,
                )
            flash.error(request, exc.message)
            return redirect("chat:conversation", pk=pk)

        payload = MessageService.serialize(message, viewer_id=request.user.id)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": True, "message": payload})
        return redirect("chat:conversation", pk=pk)


class DeleteMessageView(LoginRequiredMixin, View):
    def post(self, request, message_id):
        try:
            MessageService.delete(request.user, message_id)
        except ZynoraError as exc:
            return JsonResponse({"success": False, "message": exc.message},
                                status=exc.status_code)
        return JsonResponse({"success": True})


class MuteConversationView(LoginRequiredMixin, View):
    def post(self, request, pk):
        muted = request.POST.get("muted") == "true"
        ConversationService.mute(pk, request.user.id, muted)
        return JsonResponse({"success": True, "muted": muted})


class ArchiveConversationView(LoginRequiredMixin, View):
    def post(self, request, pk):
        ConversationService.archive(pk, request.user.id, True)
        flash.info(request, "Conversation archived.")
        return redirect("chat:inbox")

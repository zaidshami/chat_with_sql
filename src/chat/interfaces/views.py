import json
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from  chat.application.use_cases import AskDatabase
from  chat.infrastructure.repositories.django_repo import DjangoChatRepository
from  chat.infrastructure.llm.sql_chat_service import SqlChatService
from  chat.models import ChatSession, ChatMessage

def _get_or_create_session(request: HttpRequest) -> ChatSession:
    session_id = request.session.get("chat_session_id")
    if session_id and ChatSession.objects.filter(id=session_id).exists():
        return ChatSession.objects.get(id=session_id)

    sess = ChatSession.objects.create()
    request.session["chat_session_id"] = sess.id
    return sess

@require_http_methods(["GET"])
def chat_page(request: HttpRequest) -> HttpResponse:
    sess = _get_or_create_session(request)
    messages = ChatMessage.objects.filter(session=sess).order_by("created_at")
    return render(request, "chat/chat.html", {"session": sess, "messages": messages})

@require_http_methods(["POST"])
def chat_api(request: HttpRequest) -> JsonResponse:
    sess = _get_or_create_session(request)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    text = (payload.get("message") or "").strip()
    if not text:
        return JsonResponse({"error": "Message is required"}, status=400)

    use_case = AskDatabase(
        repo=DjangoChatRepository(),
        llm_service=SqlChatService(),
    )

    try:
        result = use_case.execute(session_id=sess.id, user_text=text)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"answer": result["answer"], "metadata": result.get("metadata", {})})

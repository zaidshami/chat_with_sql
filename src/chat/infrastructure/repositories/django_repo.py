from typing import Iterable
from django.db import transaction

from  chat.domain.entities import Message
from  chat.domain.repositories import ChatRepository
from  chat.models import ChatSession, ChatMessage

class DjangoChatRepository(ChatRepository):
    @transaction.atomic
    def create_session(self) -> int:
        return ChatSession.objects.create().id

    @transaction.atomic
    def add_message(self, session_id: int, message: Message) -> None:
        ChatMessage.objects.create(
            session_id=session_id,
            role=message.role,
            content=message.content,
            metadata=message.metadata or {},
        )

    def list_messages(self, session_id: int, limit: int) -> Iterable[Message]:
        qs = ChatMessage.objects.filter(session_id=session_id).order_by("-created_at")[:limit]
        for m in reversed(list(qs)):
            yield Message(role=m.role, content=m.content, metadata=m.metadata)

from dataclasses import dataclass
from typing import Dict, Any

from chat.domain.entities import Message
from chat.domain.repositories import ChatRepository
from chat.infrastructure.llm.sql_chat_service import SqlChatService

@dataclass
class AskDatabase:
    repo: ChatRepository
    llm_service: SqlChatService

    def execute(self, session_id: int, user_text: str) -> Dict[str, Any]:
        user_msg = Message(role="user", content=user_text)
        self.repo.add_message(session_id, user_msg)

        history = list(self.repo.list_messages(session_id, limit=12))
        answer = self.llm_service.ask(history)

        assistant_msg = Message(role="assistant", content=answer["answer"], metadata=answer.get("metadata"))
        self.repo.add_message(session_id, assistant_msg)

        return {"answer": assistant_msg.content, "metadata": assistant_msg.metadata or {}}

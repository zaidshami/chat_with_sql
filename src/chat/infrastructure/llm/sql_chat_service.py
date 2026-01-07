from typing import Any, Dict, List
from chat.domain.entities import Message
from .sql_agent import ask_agent

class SqlChatService:
    """Adapter between domain messages and the LangChain SQL agent."""

    def ask(self, history: List[Message], *, session_id: int) -> Dict[str, Any]:
        # LangChain expects OpenAI-style messages in the tutorial:
        messages = [{"role": m.role, "content": m.content} for m in history]
        return ask_agent(messages, session_id=session_id)

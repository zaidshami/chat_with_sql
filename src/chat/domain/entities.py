from dataclasses import dataclass
from typing import Literal, Dict, Any

Role = Literal["user", "assistant"]

@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    metadata: Dict[str, Any] | None = None

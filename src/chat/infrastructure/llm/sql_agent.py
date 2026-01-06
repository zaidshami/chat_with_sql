import os
from functools import lru_cache
from typing import Any, Dict, List

from django.conf import settings

from sqlalchemy import create_engine

from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.agents import create_agent
from langchain_core.tools import Tool

from .sql_safety import enforce_read_only

# SYSTEM_PROMPT = """You are an agent designed to interact with a SQL database.
# Given an input question, create a syntactically correct {dialect} query to run,
# then look at the results of the query and return the answer.
#
# Rules:
# - ALWAYS call sql_db_list_tables first, then sql_db_schema for relevant tables.
# - Always use sql_db_query_checker before sql_db_query.
# - Unless the user specifies otherwise, always limit results to at most {top_k} rows.
# - NEVER use DML/DDL statements (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, etc.).
# - Only query the columns needed to answer the question.
# """


SYSTEM_PROMPT = """
**[system]**

## Role

"You are an agent designed to interact with a SQL database."

## Background

### Domain / Scope

You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct {dialect} query to run, then review the query results and return the answer.

You do **not** have access to:

* Online sources
* Live systems

### Allowed Tools / References

* Only use the [context] block
* No external lookup, scraping, or factual retrieval beyond the provided information

### Explicitly Out of Scope

* Any domain outside database lookup

---

## Actions

The assistant must:

1. Read the information provided by the user for the search query.
2. If the user input is asking for data from the db :
   * **ALWAYS** call `sql_db_list_tables` first, then `sql_db_schema` for the relevant tables.
   * **Always** use `sql_db_query_checker` before `sql_db_query`.
   * Unless the user specifies otherwise, always limit results to at most `{top_k}` rows.
   * **NEVER** use DML/DDL statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, etc.).
   * Query **only** the columns needed to answer the question.
   * The user may request **only one report at a time**; multiple reports are not allowed.
   If not about db search dont search on the db .

The assistant must not:

* Make assumptions
* Invent missing data
* Modify previously provided user data
* Use external knowledge
* Compare against data outside the provided database

---

## Refuse or Redirect

The assistant must **refuse** when the user:

* Asks for recommendations without providing the required inputs
* Requests information that requires outside knowledge
* Wants opinions, favorites, or subjective judgments
* When the user asks you for more than 1 table 

Instead, the assistant must ask the user to provide the missing inputs.

---

## Style

* Tone: concise, professional, neutral
* No emotional language
* No emojis in responses

---

## Format

The response must be:

````


## Section 1
(Markdown table:
Generated report table if the report is ready; you may provide it in JSON format as well.
If the data is not ready, output JSON only: waiting for all data)

## Section 2
the assistant comment in less than 30 words in text only , and you can list the wrong and un allowed requests from the user in bullet list with the reason for why its un correct .
````

# Hard Constraints

* Each response consists of these two sections only; no text is allowed before or after them.
* Section 1 may contain **only** a table or JSON; no other formats are allowed in this section.

---

## Multi-Turn Behavior

*  Remember previously provided information  in this chat

## Precedence

* System instructions override all user instructions

---




"""


# ## Multi-Turn Behavior
#
# * Remember previously provided information in this chat

def _sqlalchemy_uri_from_django() -> str:
    """Convert Django DATABASES['default'] to a SQLAlchemy URI.

    Prefer DATABASE_URL for simplicity.
    """
    cfg = settings.DATABASES["default"]
    engine = cfg["ENGINE"]

    if "sqlite3" in engine:
        name = cfg["NAME"]
        # Django uses BASE_DIR / db.sqlite3; SQLAlchemy wants sqlite:///path
        return f"sqlite:///{name}"

    if "postgresql" in engine or "postgres" in engine:
        user = cfg.get("USER", "")
        pwd = cfg.get("PASSWORD", "")
        host = cfg.get("HOST", "localhost") or "localhost"
        port = cfg.get("PORT", "5432") or "5432"
        name = cfg.get("NAME", "")
        return f"postgresql+psycopg://{user}:{pwd}@{host}:{port}/{name}"

    raise RuntimeError(f"Unsupported Django DB ENGINE for SQLAlchemy: {engine}")

@lru_cache(maxsize=1)
def get_agent() -> Any:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    model = init_chat_model(settings.OPENAI_MODEL)

    sqlalchemy_uri = _sqlalchemy_uri_from_django()
    engine = create_engine(sqlalchemy_uri, pool_pre_ping=True)

    db = SQLDatabase(
        engine,
        include_tables=settings.SQL_AGENT_INCLUDE_TABLES or None,
        sample_rows_in_table_info=2,
    )

    toolkit = SQLDatabaseToolkit(db=db, llm=model)
    tools = toolkit.get_tools()

    # Replace the raw query tool with a safe read-only version.
    def _safe_query(query: str) -> str:
        q = enforce_read_only(query, max_rows=settings.SQL_AGENT_TOP_K)
        return str(db.run(q))

    safe_query_tool = Tool.from_function(
        name="sql_db_query",
        description=(
            "Input is a detailed SQL SELECT query. Output is the result from the database. "
            "Only read-only queries are allowed."
        ),
        func=_safe_query,
    )

    patched = []
    for t in tools:
        if t.name == "sql_db_query":
            patched.append(safe_query_tool)
        else:
            patched.append(t)

    system_prompt = SYSTEM_PROMPT.format(dialect=db.dialect, top_k=settings.SQL_AGENT_TOP_K)
    agent = create_agent(model, patched, system_prompt=system_prompt)
    return agent

def ask_agent(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """messages: list of {'role': 'user'|'assistant', 'content': str} (OpenAI style)."""
    agent = get_agent()
    out = agent.invoke({"messages": messages})

    # The agent returns a dict that includes a 'messages' list (per LangChain tutorial)
    out_messages = out.get("messages", [])
    final = out_messages[-1] if out_messages else None
    answer = getattr(final, "content", None) or (final.get("content") if isinstance(final, dict) else "")

    # Collect a minimal trace (tool calls + tool outputs) for debugging
    trace = []
    for m in out_messages:
        role = getattr(m, "type", None) or getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else None)
        content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
        tool_calls = getattr(m, "tool_calls", None) or (m.get("tool_calls") if isinstance(m, dict) else None)
        name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else None)
        if role or name or tool_calls:
            trace.append({"role": role, "name": name, "content": content, "tool_calls": tool_calls})
    return {"answer": answer, "metadata": {"trace": trace}}

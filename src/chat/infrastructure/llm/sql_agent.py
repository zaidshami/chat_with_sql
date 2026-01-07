import json
import os
from functools import lru_cache
from typing import Any, Dict, List

from django.conf import settings

from sqlalchemy import create_engine
from langchain_core.messages import SystemMessage, HumanMessage

from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.agents import create_agent
from langchain_core.tools import Tool

from .sql_safety import enforce_read_only

from chat.infrastructure.visualization.mpl_chart_service import MatplotlibChartServiceImpl
from chat.infrastructure.reporting.pdf_report_service import PdfReportServiceImpl
from chat.models import UserIntent
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

INTENT_SYSTEM_PROMPT = """
You are a strict intent extractor for a SQL assistant.

Return ONLY the structured output with these fields:
- db_request: what the user wants from the database (one sentence). If not a DB query, return "".
- wants_chart: true only if the user explicitly requested a chart/graph/plot (bar/line/pie).
- wants_pdf: true only if the user explicitly requested PDF export/download/report.

Rules:
- Do NOT infer chart/pdf if user did not ask.
- If user asks "show me results" without chart/pdf words, set both to false.
"""

def _messages_tail_for_intent(messages: List[Dict[str, str]], max_items: int = 8) -> str:
    """Compact recent context for intent extraction."""
    tail = messages[-max_items:]
    lines = []
    for m in tail:
        role = m.get("role", "")
        content = (m.get("content", "") or "").strip()
        if not content:
            continue
        # keep it short-ish per message
        if len(content) > 800:
            content = content[:800] + "…"
        lines.append(f"{role.upper()}: {content}")
    return "\n".join(lines)

def detect_user_intent(messages: List[Dict[str, str]]) -> UserIntent:
    """Use an LLM to extract 3-part intent."""
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    # Use the same model (or define settings.OPENAI_INTENT_MODEL if you want)
    intent_model = init_chat_model(getattr(settings, "OPENAI_INTENT_MODEL", settings.OPENAI_MODEL))

    # Make it deterministic if supported by your provider/model binding
    try:
        intent_model = intent_model.bind(temperature=0)
    except Exception:
        pass

    intent_llm = intent_model.with_structured_output(UserIntent)

    thread = _messages_tail_for_intent(messages)
    return intent_llm.invoke(
        [
            SystemMessage(content=INTENT_SYSTEM_PROMPT.strip()),
            HumanMessage(content=f"Conversation:\n{thread}\n\nExtract intent for the latest user request."),
        ]
    )

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
* Use build_chart or build_pdf_report only when user asks for them .
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
   * If the user asks for a PDF or chart , You have access to two tools:
  - `build_chart(table_markdown, title, chart_type)`
  - `build_pdf_report(table_markdown, title, comment, chart_path)`
    * **Do not use any charts or PDF tools unless the user explicitly asks for a chart and/or PDF.**
    * **Never show charts or PDF export, and never call `build_chart` or `build_pdf_report`, if the report data is sourced from only one table.**
      - Treat the report as "only one table" when the final SQL reads from a single base table (no JOINs, no UNION/UNION ALL across different tables, and no subqueries/CTEs that reference additional tables).
      - If the user requests a chart/PDF but the report is from only one table: return the report table only and explain the restriction in Section 2.
    * If the user asks for a chart (chart/plot/graph/bar/line/pie), and the report data is from **more than one table**, first produce the report table, then call `build_chart`.
    * If the user asks for a PDF/export/report, and the report data is from **more than one table**, call `build_pdf_report`.
    * If both chart and PDF are requested, and the report data is from **more than one table**, call `build_chart` first, then pass the returned `chart_path` into `build_pdf_report`.
    * If user didn't ask for them, or section 1 has no data dont show them .


   
   
   
   
   
   
   
   
   
* Does the user wants charts ? {dcharts}
* Does the user wants pdf export? {dpdf}
The assistant must not:

* Make assumptions
* Invent missing data
* Modify previously provided user data
* Use external knowledge
* Compare against data outside the provided database
* create charts or graphs or pdf , unless the user asks for them .

---

## Refuse or Redirect

The assistant must **refuse** when the user:

* Asks for recommendations without providing the required inputs
* Requests information that requires outside knowledge
* Wants opinions, favorites, or subjective judgments

Instead, the assistant must ask the user to provide the missing inputs.

---

## Style

* Tone: concise, professional, neutral
* No emotional language
* No emojis in responses

---

## Format

The response must be:

```

## Section 1

(Markdown table:
Generated report table if the report is ready; you may provide it in JSON format as well.
If the data is not ready, output JSON only: waiting for all data)

## Section 2

the assistant comment in less than 30 words in text only , and you can list the wrong and un allowed requests from the user in bullet list with the reason for why its un correct .


````

# Hard Constraints

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
def _get_model_and_db() -> tuple[Any, SQLDatabase]:
    """Cache the expensive parts (LLM + SQLDatabase), but build the agent per request.

    We build the agent per-request so our asset-generation tools can write outputs into
    the correct chat session folder.
    """
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
    return model, db


def _wrap_table_as_answer(table_markdown: str, comment: str = "") -> str:
    """Utility: convert a markdown table into the expected 2-section format."""
    return f"## Section 1\n{table_markdown.strip()}\n\n## Section 2\n{comment.strip()}\n"


def build_agent_for_session(session_id: int,dcharts:bool,dpdf:bool) -> Any:
    model, db = _get_model_and_db()

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

    # Chart/PDF tools (agent-callable)
    def _build_chart(table_markdown: str, title: str = "", chart_type: str = "auto") -> str:
        """Create a PNG chart from a markdown table.

        Returns JSON: {chart_url, chart_path, chart_type, ...}.
        """
        hint = (title or "").strip() or "Chart"
        if chart_type and chart_type.lower() != "auto":
            hint = f"{hint} {chart_type} chart"
        assistant_answer = _wrap_table_as_answer(table_markdown, comment="")
        meta = MatplotlibChartServiceImpl().maybe_create_chart(
            session_id=session_id,
            user_title=hint,
            assistant_answer=assistant_answer,
        )
        return json.dumps(meta)

    build_chart_tool = Tool.from_function(
        name="build_chart",
        description=(
            "Create a chart PNG from a GitHub-flavored markdown table. "
            "Inputs: table_markdown (required), title (optional), chart_type = auto|bar|line|pie (optional). "
            "Returns JSON with chart_url and chart_path."
        ),
        func=_build_chart,
    )

    def _build_pdf_report(
        table_markdown: str,
        title: str = "",
        comment: str = "",
        chart_path: str = "",
    ) -> str:
        """Create a PDF report from a markdown table (+ optional chart_path).

        Returns JSON: {report_url, report_path, ...}.
        """
        assistant_answer = _wrap_table_as_answer(table_markdown, comment=comment)
        meta = PdfReportServiceImpl().maybe_create_pdf_report(
            session_id=session_id,
            user_title=(title or "DB Report"),
            assistant_answer=assistant_answer,
            chart_path=(chart_path or None),
            llm_trace=None,
        )
        return json.dumps(meta)

    build_pdf_tool = Tool.from_function(
        name="build_pdf_report",
        description=(
            "Create a PDF report from a GitHub-flavored markdown table. "
            "Inputs: table_markdown (required), title (optional), comment (optional), chart_path (optional). "
            "Returns JSON with report_url and report_path."
        ),
        func=_build_pdf_report,
    )

    patched = []
    for t in tools:
        if t.name == "sql_db_query":
            patched.append(safe_query_tool)
        else:
            patched.append(t)

    patched.extend([build_chart_tool, build_pdf_tool])

    system_prompt = SYSTEM_PROMPT.format(dialect=db.dialect, top_k=settings.SQL_AGENT_TOP_K, dcharts=dcharts,dpdf=dpdf)
    return create_agent(model, patched, system_prompt=system_prompt)

def ask_agent(messages: List[Dict[str, str]], *, session_id: int) -> Dict[str, Any]:
    """messages: list of {'role': 'user'|'assistant', 'content': str} (OpenAI style)."""

    intent = detect_user_intent(messages)
    intent_dict = {
        "db_request": intent.db_request,
        "wants_chart": bool(intent.wants_chart),
        "wants_pdf": bool(intent.wants_pdf),
    }


    agent = build_agent_for_session(session_id,dcharts=intent_dict['wants_chart'],dpdf=intent_dict['wants_pdf'])  # keep as-is for now
    out = agent.invoke({"messages": messages})

    # The agent returns a dict that includes a 'messages' list (per LangChain tutorial)
    out_messages = out.get("messages", [])
    final = out_messages[-1] if out_messages else None
    answer = getattr(final, "content", None) or (final.get("content") if isinstance(final, dict) else "")

    # Collect a minimal trace (tool calls + tool outputs) for debugging and to extract assets
    trace = []
    for m in out_messages:
        role = getattr(m, "type", None) or getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else None)
        content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
        tool_calls = getattr(m, "tool_calls", None) or (m.get("tool_calls") if isinstance(m, dict) else None)
        name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else None)
        if role or name or tool_calls:
            trace.append({"role": role, "name": name, "content": content, "tool_calls": tool_calls})
    extracted: Dict[str, Any] = {}
    for item in trace:
        name = item.get("name")
        if name not in ("build_chart", "build_pdf_report"):
            continue
        raw = item.get("content")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict):
            extracted.update(data)
    return {"answer": answer, "metadata": {"intent": intent_dict, "trace": trace, **extracted}}

    # return {"answer": answer, "metadata": {"trace": trace, **extracted}}
#
# def ask_agent(messages: List[Dict[str, str]], *, session_id: int) -> Dict[str, Any]:
#     """messages: list of {'role': 'user'|'assistant', 'content': str} (OpenAI style)."""
#     agent = build_agent_for_session(session_id)
#     out = agent.invoke({"messages": messages})
#
#     # The agent returns a dict that includes a 'messages' list (per LangChain tutorial)
#     out_messages = out.get("messages", [])
#     final = out_messages[-1] if out_messages else None
#     answer = getattr(final, "content", None) or (final.get("content") if isinstance(final, dict) else "")
#
#     # Collect a minimal trace (tool calls + tool outputs) for debugging and to extract assets
#     trace = []
#     for m in out_messages:
#         role = getattr(m, "type", None) or getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else None)
#         content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
#         tool_calls = getattr(m, "tool_calls", None) or (m.get("tool_calls") if isinstance(m, dict) else None)
#         name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else None)
#         if role or name or tool_calls:
#             trace.append({"role": role, "name": name, "content": content, "tool_calls": tool_calls})
#     extracted: Dict[str, Any] = {}
#     for item in trace:
#         name = item.get("name")
#         if name not in ("build_chart", "build_pdf_report"):
#             continue
#         raw = item.get("content")
#         if not isinstance(raw, str) or not raw.strip():
#             continue
#         try:
#             data = json.loads(raw)
#         except Exception:
#             continue
#         if isinstance(data, dict):
#             extracted.update(data)
#
#     return {"answer": answer, "metadata": {"trace": trace, **extracted}}

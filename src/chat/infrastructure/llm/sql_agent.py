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
from langchain_core.tools import StructuredTool

from .prompts_texts import SYSTEM_PROMPT, INTENT_SYSTEM_PROMPT
from .sql_safety import enforce_read_only
from chat.models import  BuildChartArgs
from chat.models import  BuildPdfArgs
from chat.infrastructure.visualization.mpl_chart_service import MatplotlibChartServiceImpl
from chat.infrastructure.reporting.pdf_report_service import PdfReportServiceImpl
from chat.models import UserIntent


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



    build_chart_tool = StructuredTool.from_function(
        name="build_chart",
        description=(
            "Create a chart PNG from a GitHub-flavored markdown table. "
            "Inputs: table_markdown (required), title (optional), chart_type = auto|bar|line|pie (optional). "
            "Returns JSON with chart_url and chart_path."
        ),
        func=_build_chart,
        args_schema=BuildChartArgs,

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

    build_pdf_tool = StructuredTool.from_function(
        name="build_pdf_report",
        description=(
            "Create a PDF report from a GitHub-flavored markdown table. "
            "Inputs: table_markdown (required), title (optional), comment (optional), chart_path (optional). "
            "Returns JSON with report_url and report_path."
        ),
        func=_build_pdf_report,
        args_schema=BuildPdfArgs,
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

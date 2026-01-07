from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.conf import settings

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

from chat.domain.services import ReportService
from .markdown_report_parser import parse_assistant_answer


@dataclass(frozen=True)
class PdfReportResult:
    report_path: str
    report_url: str
    filename: str


class PdfReportServiceImpl(ReportService):
    """Generate a PDF report from the agent's "Section 1" markdown table."""

    def maybe_create_pdf_report(
        self,
        *,
        session_id: int,
        user_title: str,
        assistant_answer: str,
        chart_path: str | None = None,
        llm_trace: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        parsed = parse_assistant_answer(assistant_answer)
        if not parsed.table:
            return {}

        # Ensure media settings exist
        media_root = getattr(settings, "MEDIA_ROOT", None)
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if not media_root:
            return {}

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_session = str(session_id)
        out_dir = os.path.join(str(media_root), "reports", f"session_{safe_session}")
        os.makedirs(out_dir, exist_ok=True)
        filename = f"report_{ts}.pdf"
        out_path = os.path.join(out_dir, filename)

        self._build_pdf(
            out_path=out_path,
            title=user_title.strip()[:120] or "DB Report",
            executed_sql=_extract_last_sql(llm_trace),
            comment=parsed.section2_raw.strip(),
            table=parsed.table,
            chart_path=chart_path,
            generated_utc=ts,
        )

        # Build URL relative to MEDIA_URL
        rel_path = f"reports/session_{safe_session}/{filename}".replace("\\", "/")
        report_url = f"{media_url.rstrip('/')}/{rel_path}"
        return {
            "report_url": report_url,
            "report_path": out_path,
            "report_filename": filename,
        }

    def _build_pdf(
        self,
        *,
        out_path: str,
        title: str,
        executed_sql: str | None,
        comment: str,
        table: List[List[str]],
        chart_path: str | None,
        generated_utc: str,
    ) -> None:
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            out_path,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        story: List[Any] = []
        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(f"Generated (UTC): {generated_utc}", styles["Normal"]))

        if executed_sql:
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph("Executed SQL:", styles["Heading3"]))
            story.append(Paragraph(f"<font name='Courier'>{_escape_xml(executed_sql)}</font>", styles["BodyText"]))

        if comment:
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(comment, styles["Italic"]))

        story.append(Spacer(1, 0.6 * cm))

        # Optional chart image
        if chart_path and os.path.exists(chart_path):
            printable_w = A4[0] - doc.leftMargin - doc.rightMargin
            # Keep a conservative height so the chart fits on the first page in most cases
            story.append(Paragraph("Chart:", styles["Heading3"]))
            story.append(Spacer(1, 0.2 * cm))
            story.append(Image(chart_path, width=printable_w, height=printable_w * 0.5))
            story.append(Spacer(1, 0.5 * cm))

        # Convert cells to Paragraphs for wrapping
        def cell(x: str) -> Paragraph:
            return Paragraph((x or "").replace("\n", "<br/>") , styles["BodyText"])  # noqa: E501

        data = [[cell(c) for c in row] for row in table]

        # Column widths: distribute evenly within printable width
        printable_w = A4[0] - doc.leftMargin - doc.rightMargin
        col_count = max(1, len(data[0]))
        col_w = [printable_w / col_count] * col_count

        t = Table(data, colWidths=col_w, hAlign="LEFT")
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                ]
            )
        )
        story.append(t)
        doc.build(story)


def _extract_last_sql(llm_trace: Dict[str, Any] | None) -> Optional[str]:
    """Best-effort extraction of the last SQL statement from the LangChain trace."""
    if not llm_trace:
        return None

    # The trace format is a list of message dicts from the agent loop.
    if isinstance(llm_trace, list):
        for item in reversed(llm_trace):
            tool_calls = item.get("tool_calls") if isinstance(item, dict) else None
            if not tool_calls:
                continue
            # tool_calls can be list[dict] with `name` and `args` or OpenAI-style `function`.
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                name = tc.get("name")
                if not name and isinstance(tc.get("function"), dict):
                    name = tc["function"].get("name")
                if name != "sql_db_query":
                    continue

                args = tc.get("args")
                if args is None and isinstance(tc.get("function"), dict):
                    args = tc["function"].get("arguments")

                if isinstance(args, dict):
                    q = args.get("query")
                    if isinstance(q, str) and q.strip():
                        return q.strip()

                # OpenAI-style arguments may be JSON string
                if isinstance(args, str) and args.strip():
                    # keep as-is (already JSON) to avoid fragile parsing
                    return args.strip()
    return None


def _escape_xml(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&#39;")
    )

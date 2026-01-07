from typing import Protocol, Any, Dict


class ChartService(Protocol):
    """Generate charts (e.g., PNG) from assistant outputs."""

    def maybe_create_chart(
        self,
        *,
        session_id: int,
        user_title: str,
        assistant_answer: str,
    ) -> Dict[str, Any]:
        """Create a chart image when the assistant output contains a single report table.

        Returns a dict with optional keys like:
        - chart_url: str
        - chart_path: str
        - chart_filename: str
        - chart_type: str

        If no chart can/should be generated, return an empty dict.
        """
        ...


class ReportService(Protocol):
    """Generate user-facing reports (e.g., PDF) from assistant outputs."""

    def maybe_create_pdf_report(
        self,
        *,
        session_id: int,
        user_title: str,
        assistant_answer: str,
        chart_path: str | None = None,
        llm_trace: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Create a PDF report when the assistant output contains a single report table.

        llm_trace can be provided (agent trace) to include executed SQL in the report.

        Returns a dict with optional keys like:
        - report_url: str
        - report_path: str
        - report_filename: str

        If no report can/should be generated, return an empty dict.
        """
        ...

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

from chat.domain.services import ChartService
from chat.infrastructure.reporting.markdown_report_parser import parse_assistant_answer


_NUM_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^-?\d+(?:\.\d+)?$")


def _to_float(x: str) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    # Remove common formatting
    s = s.replace("$", "").replace("%", "")
    s = s.replace(" ", "")
    # Handle 1,234.56
    if _NUM_RE.match(s):
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None
    return None


def _is_date_like(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    # ISO-ish forms
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m"):
        try:
            datetime.strptime(s, fmt)
            return True
        except ValueError:
            pass
    return False


def _majority_date_like(values: List[str]) -> bool:
    if not values:
        return False
    ok = sum(1 for v in values if _is_date_like(v))
    return ok >= max(2, int(len(values) * 0.6))


def _wants_chart(user_title: str) -> bool:
    s = (user_title or "").lower()
    # We generate charts by default when possible, but still detect explicit intent.
    return any(k in s for k in ("chart", "plot", "graph", "bar", "line", "pie"))


def _requested_chart_type(user_title: str) -> Optional[str]:
    s = (user_title or "").lower()
    if "pie" in s:
        return "pie"
    if "bar" in s:
        return "bar"
    if "line" in s:
        return "line"
    return None


@dataclass(frozen=True)
class _ChartSpec:
    chart_type: str
    x_label: str
    y_labels: List[str]
    x_values: List[str]
    y_series: List[List[float]]  # len == len(y_labels)


class MatplotlibChartServiceImpl(ChartService):
    """Create a PNG chart from the assistant markdown table in Section 1."""

    def maybe_create_chart(
        self,
        *,
        session_id: int,
        user_title: str,
        assistant_answer: str,
    ) -> Dict[str, Any]:
        parsed = parse_assistant_answer(assistant_answer)
        if not parsed.table:
            return {}

        media_root = getattr(settings, "MEDIA_ROOT", None)
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if not media_root:
            return {}

        spec = _infer_chart_spec(parsed.table, user_title)
        if not spec:
            return {}

        # If the user explicitly asked for no chart, respect it.
        if "no chart" in (user_title or "").lower():
            return {}

        # Generate chart
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_session = str(session_id)
        out_dir = os.path.join(str(media_root), "charts", f"session_{safe_session}")
        os.makedirs(out_dir, exist_ok=True)
        filename = f"chart_{ts}.png"
        out_path = os.path.join(out_dir, filename)

        self._render_chart(out_path=out_path, title=_short_title(user_title), spec=spec)

        rel_path = f"charts/session_{safe_session}/{filename}".replace("\\", "/")
        chart_url = f"{media_url.rstrip('/')}/{rel_path}"
        return {
            "chart_url": chart_url,
            "chart_path": out_path,
            "chart_filename": filename,
            "chart_type": spec.chart_type,
        }

    def _render_chart(self, *, out_path: str, title: str, spec: _ChartSpec) -> None:
        # Import matplotlib lazily so Django startup stays fast.
        import matplotlib

        matplotlib.use("Agg")  # headless
        import matplotlib.pyplot as plt

        # Basic readability limits
        max_points = 50
        x = spec.x_values[:max_points]
        y_series = [ys[:max_points] for ys in spec.y_series]

        plt.figure(figsize=(10, 4.8))
        if title:
            plt.title(title)

        if spec.chart_type == "pie":
            # Use first series only
            ys = y_series[0]
            # Guard against negatives (pie doesn't make sense)
            ys = [max(0.0, v) for v in ys]
            if sum(ys) == 0:
                ys = [1.0 for _ in ys]
            plt.pie(ys, labels=x, autopct="%1.1f%%")
        elif spec.chart_type == "line":
            for idx, ys in enumerate(y_series[:3]):
                plt.plot(x, ys, marker="o", linewidth=1.8, label=spec.y_labels[idx])
            plt.xlabel(spec.x_label)
            plt.ylabel(", ".join(spec.y_labels[:3]))
            if len(y_series) > 1:
                plt.legend(loc="best")
            plt.xticks(rotation=35, ha="right")
            plt.grid(True, alpha=0.25)
        else:  # bar (default)
            ys = y_series[0]
            plt.bar(x, ys)
            plt.xlabel(spec.x_label)
            plt.ylabel(spec.y_labels[0])
            plt.xticks(rotation=35, ha="right")
            plt.grid(True, axis="y", alpha=0.25)

        plt.tight_layout()
        plt.savefig(out_path, dpi=160)
        plt.close()


def _short_title(user_title: str) -> str:
    t = (user_title or "").strip()
    return t[:90] + ("…" if len(t) > 90 else "")


def _infer_chart_spec(table: List[List[str]], user_title: str) -> Optional[_ChartSpec]:
    header = table[0]
    rows = table[1:]
    if not header or not rows:
        return None

    col_count = len(header)
    # Identify numeric columns
    numeric_cols: List[int] = []
    numeric_data: Dict[int, List[float]] = {}

    for c in range(col_count):
        floats: List[Optional[float]] = [_to_float(r[c]) if c < len(r) else None for r in rows]
        ok = sum(1 for v in floats if v is not None)
        if ok >= max(2, int(len(rows) * 0.6)):
            numeric_cols.append(c)
            numeric_data[c] = [float(v) if v is not None else 0.0 for v in floats]

    if not numeric_cols:
        return None

    # Choose x column: first non-numeric column if possible; else first column.
    x_idx = next((i for i in range(col_count) if i not in numeric_cols), 0)
    x_values = [str(r[x_idx]) if x_idx < len(r) else "" for r in rows]
    x_label = header[x_idx] if x_idx < len(header) else "x"

    # Select chart type
    requested = _requested_chart_type(user_title)
    x_is_date = _majority_date_like(x_values)

    if requested == "pie":
        # Pie only works with a single numeric series and categorical x
        y_idx = numeric_cols[0]
        return _ChartSpec(
            chart_type="pie",
            x_label=x_label,
            y_labels=[header[y_idx]],
            x_values=x_values,
            y_series=[numeric_data[y_idx]],
        )

    if requested == "line" or x_is_date:
        y_idxs = numeric_cols[:3]
        return _ChartSpec(
            chart_type="line",
            x_label=x_label,
            y_labels=[header[i] for i in y_idxs],
            x_values=x_values,
            y_series=[numeric_data[i] for i in y_idxs],
        )

    # Default to bar chart, using the first numeric column
    y_idx = numeric_cols[0]
    return _ChartSpec(
        chart_type="bar",
        x_label=x_label,
        y_labels=[header[y_idx]],
        x_values=x_values,
        y_series=[numeric_data[y_idx]],
    )

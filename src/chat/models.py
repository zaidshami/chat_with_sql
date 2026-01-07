from django.db import models
from pydantic import BaseModel, Field
class ChatSession(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

class ChatMessage(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [(ROLE_USER, "User"), (ROLE_ASSISTANT, "Assistant")]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class UserIntent(BaseModel):
    db_request: str = Field(
        description="One-sentence description of what the user wants from the database. Empty string if not a DB request."
    )
    wants_chart: bool = Field(
        description="True only if the user explicitly asked for a chart/graph/plot (bar/line/pie)."
    )
    wants_pdf: bool = Field(
        description="True only if the user explicitly asked for PDF export/download/report."
    )

class BuildChartArgs(BaseModel):
    table_markdown: str = Field(..., description="Markdown pipe table")
    title: str = Field("Chart", description="Chart title")
    chart_type: str = Field("auto", description="auto|bar|line|pie")


class BuildPdfArgs(BaseModel):
    table_markdown: str = Field(..., description="Markdown pipe table to include in the PDF")
    title: str = Field("Report", description="Report title")
    comment: str = Field("", description="Short description to include in the report")
    chart_path: str | None = Field(None, description="Optional absolute path to a chart image")
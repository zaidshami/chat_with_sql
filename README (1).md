# SQL Reporting Chatbot (Charts & PDF Export)

## Overview
This repository contains a **scope-restricted AI chatbot** designed to help users **query and understand database reports** through natural language conversation. The bot can answer reporting questions by executing **safe, read-only SQL** against a configured SQL database and returning the results in a **fixed, predictable output format**.

When the user explicitly requests it, the bot can also:
- Generate **data visualizations (charts)** for the report, and/or
- Export the report (and chart, if applicable) as a **downloadable PDF**.

This project is intended for professional settings where **reliability, access control, and strict adherence to requirements** are essential.

---

## Core Use Case
- Chat with the bot to request **business/operational reports** stored in a SQL database.
- Optionally request:
  - A **chart** (one of three supported types), and/or
  - A **PDF export** of the report output.

Example questions:
- “Customers with orders count?”
- “Show total sales per product.”
- “Plot orders per month as a line chart.”
- “Generate a PDF for this report.”

---

## Key Features
### 1) Agent-Based Tooling (3 Agent Tools)
The model is equipped with **three agent tools** and can **select and invoke the appropriate tool** depending on the user’s request and the current conditions:

1. **SQL Reporting Tool**
   - Generates and runs **read-only SQL** to answer reporting questions.
   - Returns results grounded in actual database output.

2. **Chart Generation Tool**
   - Creates charts **only when requested** by the user.
   - Supports **three chart types** (e.g., *bar*, *line*, *pie*) based on user intent.

3. **PDF Report Tool**
   - Produces a **PDF** representation of the report.
   - Optionally embeds the generated chart when a chart is requested alongside the PDF.

Tool selection is **policy-driven** and tied to the detected intent (report-only vs. report+chart vs. report+pdf).

---

### 2) Database Connectivity
- Designed to connect to **any SQL database supported by SQLAlchemy** (subject to installed drivers).
- Connection configuration is centralized and environment-friendly (e.g., via `DATABASE_URL`).

---

### 3) Strict Scope and Policy Compliance
The agent is intentionally constrained to ensure professional reliability:
- **Out-of-scope refusal:** It will not answer questions unrelated to SQL reporting.
- **Read-only policy:** It is restricted to non-mutating SQL operations.
- **No unsolicited actions:** It does not generate charts or PDFs unless asked.

---

### 4) Fixed Response Schema (Two Sections Only)
All bot responses follow the same **two-part format** and cannot be changed by the user:

1. **Report Answer**
   - A concise explanation and/or a table derived **only** from the executed query results.

2. **Artifacts**
   - Includes `chart` and/or `pdf` references **only if** the user requested them.
   - Otherwise, it explicitly states that no artifacts were generated.

This predictable contract simplifies integration with front-end UIs and downstream services.

---

## Safety & Anti-Hallucination Principles
This system is designed to reduce incorrect or fabricated output by:
- Grounding report answers in **executed SQL results**
- Enforcing **scope boundaries**
- Refusing irrelevant prompts
- Returning only the artifacts the user requested

> “No hallucinations” here means the bot does not invent data or claims outside the database results and refuses requests beyond its reporting scope.

---

## High-Level Architecture
- **UI / Presentation Layer**
  - Chat interface for submitting questions and receiving results and download links.

- **Application Layer**
  - Orchestrates intent detection, tool selection, query execution, and artifact generation.

- **Domain Layer**
  - Policies: scope control, response schema enforcement, read-only constraints.

- **Infrastructure Layer**
  - SQL connection/queries via SQLAlchemy
  - Chart rendering (e.g., Matplotlib)
  - PDF generation service

---

## Configuration (High Level)
### Environment Variables
- `DATABASE_URL` — SQLAlchemy database URL.

Examples:
- PostgreSQL: `postgresql+psycopg://user:pass@localhost:5432/appdb`
- MySQL: `mysql+pymysql://user:pass@localhost:3306/appdb`
- SQLite: `sqlite:///local.db`

### Recommended Database Permissions
Use a database account with:
- **Read-only privileges**
- Access limited to reporting schemas/tables

---

## How to Use
1. Start the application (web server / API) and open the chat UI.
2. Ask a reporting question.
3. Optionally request:
   - “as a **bar/line/pie chart**”
   - “**export as PDF**”
   - “**chart and PDF**”

---

## Extensibility
Common extensions include:
- Additional chart types
- Additional export formats (CSV/XLSX)
- A curated catalog of approved reports with semantic aliases
- Role-based access control and audit logging

---

## License
Internal / Proprietary (adjust as needed).

---

## Contact
For hiring review or technical discussion, please include:
- A brief deployment guide (optional)
- A sanitized schema sample (optional)
- A short demo video (optional)

# DBChat Pro (Django + LangChain + OpenAI) — Clean Architecture Starter

A “pro” Django starter that exposes a **single chat UI** where users can ask questions about data in your **SQL database**.
Under the hood it uses a **LangChain SQL agent** with an extra **read-only SQL guard** (only `SELECT` / `WITH`).

## Features

- Django project with **split settings** (`base.py`, `local.py`, `production.py`)
- Clean-ish architecture inside the `chat` app:
  - `domain/` (entities + repository interfaces)
  - `application/` (use cases)
  - `infrastructure/` (Django ORM + LangChain agent + DB adapters)
  - `interfaces/` (Django views + templates)
- Sample `store` app with seed data (Customers/Products/Orders) so you can test immediately
- Read-only SQL execution guard + enforced `LIMIT`
- Docker Compose for Postgres (optional)

---

## Quickstart (SQLite)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
python manage.py migrate
python manage.py seed_store
python manage.py runserver
```

Open: http://127.0.0.1:8000/chat/

---

## Quickstart (Postgres via Docker)

```bash
cp .env.example .env
docker compose up -d db
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_store
python manage.py runserver
```

---

## Environment variables

See `.env.example`.

**Important:** for safety, create a **read-only database user** for the agent in production.

---

## Tests

```bash
pytest
```

---

## Notes on safety

LangChain’s docs explicitly warn about risks of executing model-generated SQL.
We add two layers:
1) the agent system prompt forbids DML
2) the server **validates and rejects** non-read queries before execution

Still, run this with **least privilege** DB credentials.

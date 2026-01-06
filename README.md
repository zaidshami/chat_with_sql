
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


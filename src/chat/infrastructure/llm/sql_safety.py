import re

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|attach|pragma|vacuum)\b",
    re.IGNORECASE,
)

def enforce_read_only(sql: str, *, max_rows: int) -> str:
    q = (sql or "").strip()

    # Strip trailing semicolon
    if q.endswith(";"):
        q = q[:-1].strip()

    # Disallow multiple statements
    if ";" in q:
        raise ValueError("Multiple SQL statements are not allowed.")

    if FORBIDDEN.search(q):
        raise ValueError("Only read-only SQL is allowed (SELECT/WITH).")

    if not (q.lower().startswith("select") or q.lower().startswith("with")):
        raise ValueError("Only read-only SQL is allowed (SELECT/WITH).")

    # Enforce a LIMIT if absent (best-effort)
    # if " limit " not in q.lower():
    #     q = f"{q} LIMIT {max_rows}"

    return q

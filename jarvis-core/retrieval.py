import re
import sqlite3
from contextlib import closing
from pathlib import Path

from security import check_path


STOP_WORDS = {
    "the", "and", "that", "this", "with", "from", "have",
    "what", "when", "where", "who", "why", "how", "are",
    "was", "were", "your", "you", "about", "into", "for",
    "but", "not", "can", "could", "would", "should", "does",
    "did", "has", "had", "its", "it's", "my", "me", "i",
    "a", "an", "of", "to", "in", "on", "is", "it"
}


def _tokens(text):
    words = re.findall(r"[A-Za-z0-9_+#.-]+", text.casefold())
    cleaned = (word.strip("._-") for word in words)
    return {word for word in cleaned if len(word) >= 3 and word not in STOP_WORDS}


def _match_score(query_tokens, content):
    """Match whole terms so a short query cannot hit an unrelated substring."""
    return len(query_tokens & _tokens(content))


def relevant_context(query, limit=6, db_path=None):
    db_path = check_path(Path(db_path) if db_path is not None else Path(__file__).parent / "data" / "jarvis.db")

    if not db_path.exists():
        return []

    query_tokens = _tokens(query)

    if not query_tokens:
        return []

    candidates = []
    # Stream the lifetime tables, retaining only the best distinct results.
    # This preserves ranking/old-note recall without allocating every row.
    keep = max(1, limit)
    def add_candidate(item):
        normalized = item['text'].strip().lower()
        for previous in candidates:
            if previous['text'].strip().lower() == normalized:
                if (previous['score'], previous['id']) >= (item['score'], item['id']):
                    return
                candidates.remove(previous)
                break
        candidates.append(item)
        candidates.sort(key=lambda candidate: (candidate['score'], candidate['id']), reverse=True)
        del candidates[keep:]

    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row

        for table, source, bonus in (
            ("facts", "user fact", 2),
            ("preferences", "preference", 1),
            ("project_state", "project state", 1),
        ):
            try:
                rows = db.execute(f"SELECT key, value FROM {table}")
                for row in rows:
                    content = f"{row['key']}: {row['value']}"
                    score = 2 * _match_score(query_tokens, row["key"])
                    score += _match_score(query_tokens, row["value"])
                    if score:
                        add_candidate({
                            "score": score + bonus,
                            "text": content,
                            "source": source,
                            "id": 0,
                        })
            except sqlite3.OperationalError:
                pass

        try:
            rows = db.execute("""
                SELECT id, kind, content, source, created_at
                FROM memories
                ORDER BY id DESC
            """)

            for row in rows:
                content = row["content"]
                score = _match_score(query_tokens, content)

                if score:
                    add_candidate({
                        "score": score + 0.5,
                        "text": content,
                        "source": f"memory:{row['kind']}",
                        "id": row["id"],
                    })
        except sqlite3.OperationalError:
            pass

        # Retrieve bounded matching Master history without loading its lifetime transcript.
        # Side messages stay outside retrieval until explicitly moved to Master.
        try:
            db.create_function("jarvis_match_score", 1, lambda content: _match_score(query_tokens, content))
            terms = sorted(query_tokens)[:8]
            predicates = " OR ".join("m.content LIKE ? ESCAPE '\\'" for _ in terms)
            patterns = ["%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for term in terms]
            rows = db.execute(
                "SELECT m.id, m.role, m.content, jarvis_match_score(m.content) AS match_score "
                "FROM conversation_messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.is_master = 1 AND (" + predicates + ") "
                "ORDER BY CASE WHEN match_score > 0 THEN match_score + CASE WHEN m.role = 'user' THEN 1 ELSE -0.25 END ELSE -1 END DESC, m.id DESC LIMIT 80", patterns,
            )
            for row in rows:
                score = row["match_score"]
                if score:
                    add_candidate({"score": score + (1 if row["role"] == "user" else -.25),
                                       "text": row["content"], "source": "Master " + row["role"] + " message", "id": row["id"]})
        except sqlite3.OperationalError:
            pass

        try:
            rows = db.execute("""
                SELECT id, role, content, created_at
                FROM messages
                ORDER BY id DESC
            """)

            for row in rows:
                content = row["content"]
                score = _match_score(query_tokens, content)

                if score:
                    if row["role"] == "user":
                        score += 1
                    elif row["role"] == "assistant":
                        score -= 0.25

                    add_candidate({
                        "score": score,
                        "text": content,
                        "source": f"past {row['role']} message",
                        "id": row["id"],
                    })
        except sqlite3.OperationalError:
            pass

    candidates.sort(
        key=lambda item: (item["score"], item["id"]),
        reverse=True
    )

    results = []
    seen = set()

    for item in candidates:
        normalized = item["text"].strip().lower()

        if normalized in seen:
            continue

        seen.add(normalized)
        results.append(item)

        if len(results) >= limit:
            break

    return results

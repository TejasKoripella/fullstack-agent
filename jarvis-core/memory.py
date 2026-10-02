import sqlite3
from pathlib import Path
from contextlib import contextmanager
from security import assert_not_admin, check_path


class MemoryStore:
    def __init__(self, db_path=None):
        assert_not_admin()
        if db_path is None:
            db_path = Path(__file__).resolve().parent / "data" / "jarvis.db"
        self.db_path = check_path(Path(db_path))

    def _require_approval(self, approved):
        if not approved:
            raise PermissionError(
                "Persistent memory writes require explicit user approval."
            )

    @contextmanager
    def _connect(self, readonly=False):
        db = (sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)
              if readonly else sqlite3.connect(self.db_path))
        try:
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()

    def initialize(self, approved=False):
        self._require_approval(approved)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS project_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    target TEXT,
                    approved INTEGER NOT NULL,
                    allowed INTEGER NOT NULL,
                    reason TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision = 'allow'),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(action_type, target)
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK(kind IN ('main', 'side')),
                    title TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS conversation_messages_by_chat
                    ON conversation_messages(conversation_id, id);
            """)
            existing = {row[1] for row in db.execute("PRAGMA table_info(audit_log)")}
            for column, definition in {
                "authorization_source": "TEXT",
                "security_result": "TEXT",
                "execution_result": "TEXT",
                "latency_ms": "INTEGER",
            }.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE audit_log ADD COLUMN {column} {definition}")

            columns = {row[1] for row in db.execute("PRAGMA table_info(conversations)")}
            for column, definition in {"is_master": "INTEGER NOT NULL DEFAULT 0", "merged_into": "INTEGER", "original_title": "TEXT"}.items():
                if column not in columns:
                    db.execute(f"ALTER TABLE conversations ADD COLUMN {column} {definition}")
            db.execute("UPDATE conversations SET original_title = title WHERE original_title IS NULL")
            message_columns = {row[1] for row in db.execute("PRAGMA table_info(conversation_messages)")}
            if "origin_conversation_id" not in message_columns:
                db.execute("ALTER TABLE conversation_messages ADD COLUMN origin_conversation_id INTEGER")
            db.execute("UPDATE conversation_messages SET origin_conversation_id = conversation_id WHERE origin_conversation_id IS NULL")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_master_chat ON conversations(is_master) WHERE is_master = 1")
            # Migrate once without deleting history, source conversations, or long-term memories.
            master = db.execute("SELECT id FROM conversations WHERE is_master = 1").fetchone()
            if master is None:
                master = db.execute("SELECT id FROM conversations WHERE kind = 'main' ORDER BY id LIMIT 1").fetchone()
                if master is None:
                    master_id = db.execute("INSERT INTO conversations(kind, title, original_title, is_master) VALUES ('main', 'Master Chat', 'Master Chat', 1)").lastrowid
                else:
                    master_id = master[0]
                    db.execute("UPDATE conversations SET is_master = 1, title = 'Master Chat' WHERE id = ?", (master_id,))
                db.execute("UPDATE conversation_messages SET conversation_id = ? WHERE conversation_id IN (SELECT id FROM conversations WHERE kind = 'main' AND id != ?)", (master_id, master_id))
                db.execute("UPDATE conversations SET merged_into = ? WHERE kind = 'main' AND id != ?", (master_id, master_id))
                db.execute("INSERT INTO audit_log(action, target, approved, allowed, reason) VALUES ('migrate_master_chat', ?, 1, 1, 'History preserved with source conversation IDs; memory unchanged')", (str(master_id),))
            else:
                master_id = master[0]
                db.execute("UPDATE conversation_messages SET conversation_id = ? WHERE conversation_id IN (SELECT id FROM conversations WHERE kind = 'main' AND is_master = 0 AND merged_into IS NULL)", (master_id,))
                db.execute("UPDATE conversations SET merged_into = ? WHERE kind = 'main' AND is_master = 0 AND merged_into IS NULL", (master_id,))
            empty_sides = db.execute("UPDATE conversations SET merged_into = ? WHERE kind = 'side' AND merged_into IS NULL AND NOT EXISTS (SELECT 1 FROM conversation_messages WHERE conversation_id = conversations.id)", (master_id,))
            if empty_sides.rowcount:
                db.execute("INSERT INTO audit_log(action, target, approved, allowed, reason) VALUES ('archive_empty_side_drafts', ?, 1, 1, 'Legacy empty rows preserved as archives; no messages removed')", (str(empty_sides.rowcount),))

    @staticmethod
    def _chat_metadata(row) -> dict:
        chat = dict(row)
        chat["kind"] = "master" if chat.pop("is_master", 0) else "archive" if chat.get("merged_into") else chat["kind"]
        return chat

    def master_conversation(self) -> dict:
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM conversations WHERE is_master = 1").fetchone()
        if row is None:
            raise RuntimeError("Master Chat has not been initialized.")
        return self._chat_metadata(row)

    def conversation_metadata(self, chat_id: int) -> dict | None:
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM conversations WHERE id = ?", (chat_id,)).fetchone()
        return self._chat_metadata(row) if row is not None else None

    def structured_context(self, limit=9) -> list[str]:
        with self._connect(readonly=True) as db:
            rows = []
            for table, kind in (("facts", "user fact"), ("preferences", "preference"), ("project_state", "project")):
                rows.extend(db.execute(f"SELECT ?, key, value FROM {table} ORDER BY updated_at DESC, key LIMIT ?", (kind, max(1, limit // 3))).fetchall())
            rows = rows[:limit]
        return [f"{kind} {key[:100]}: {value[:400]}" for kind, key, value in rows]

    def create_conversation(self, kind="main", title="Side Chat", approved=False,
                            first_message=None, first_reply=None) -> dict:
        self._require_approval(approved)
        if kind in {"main", "master"}:
            return self.master_conversation()
        if kind != "side":
            raise ValueError("Unknown conversation kind.")
        if not all(isinstance(text, str) and text.strip() and len(text) <= 8000
                   for text in (first_message, first_reply)):
            raise ValueError("Side Chat is created only after its first successful exchange.")
        title = title.strip()[:100] or "New chat"
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO conversations (kind, title, original_title) VALUES (?, ?, ?)", (kind, title, title)
            )
            chat_id = cursor.lastrowid
            db.executemany(
                "INSERT INTO conversation_messages(conversation_id, origin_conversation_id, role, content) VALUES (?, ?, ?, ?)",
                ((chat_id, chat_id, "user", first_message.strip()), (chat_id, chat_id, "assistant", first_reply.strip())),
            )
        return {"id": chat_id, "kind": kind, "title": title}

    def list_conversations(self, kind="main") -> list[dict]:
        if kind in {"main", "master"}:
            return [self.master_conversation()]
        if kind != "side":
            raise ValueError("Unknown conversation kind.")
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM conversations "
                "WHERE kind = ? AND merged_into IS NULL ORDER BY updated_at DESC, id DESC", (kind,)
            ).fetchall()
        return [self._chat_metadata(row) for row in rows]

    def get_conversation(self, chat_id: int) -> dict | None:
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (chat_id,),
            ).fetchone()
            if row is None:
                return None
            archive = row["merged_into"] is not None
            messages = db.execute(
                "SELECT id, role, content, created_at FROM conversation_messages "
                + ("WHERE origin_conversation_id = ? ORDER BY id" if archive else "WHERE conversation_id = ? ORDER BY id"), (chat_id,),
            ).fetchall()
        return {**self._chat_metadata(row), "messages": [dict(item) for item in messages]}

    def conversation_history(self, chat_id: int, limit=12) -> list[dict]:
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            exists = db.execute("SELECT 1 FROM conversations WHERE id = ? AND merged_into IS NULL", (chat_id,)).fetchone()
            if not exists:
                raise ValueError("Conversation not found.")
            rows = db.execute(
                "SELECT role, content FROM conversation_messages WHERE conversation_id = ? "
                "ORDER BY id DESC LIMIT ?", (chat_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_conversation_message(self, chat_id: int, role: str, content: str, approved=False) -> None:
        self._require_approval(approved)
        if role not in {"user", "assistant"} or not content.strip() or len(content) > 8000:
            raise ValueError("Invalid conversation message.")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM conversations WHERE id = ? AND merged_into IS NULL", (chat_id,)).fetchone() is None:
                raise ValueError("Conversation not found or archived.")
            cursor = db.execute(
                "INSERT INTO conversation_messages (conversation_id, origin_conversation_id, role, content) VALUES (?, ?, ?, ?)",
                (chat_id, chat_id, role, content.strip()),
            )
            db.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,)
            )
        if cursor.lastrowid is None:
            raise ValueError("Conversation not found.")

    def rename_conversation(self, chat_id: int, title: str, approved=False) -> bool:
        self._require_approval(approved)
        title = title.strip()
        if not title or len(title) > 100:
            raise ValueError("Conversation title must be 1 to 100 characters.")
        with self._connect() as db:
            row = db.execute("SELECT is_master, merged_into FROM conversations WHERE id = ?", (chat_id,)).fetchone()
            if row and (row[0] or row[1] is not None):
                raise PermissionError("Master Chat and preserved archives cannot be renamed.")
            result = db.execute(
                "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, chat_id),
            )
        return result.rowcount > 0

    def promote_conversation(self, chat_id: int, approved=False) -> bool:
        self._require_approval(approved)
        with self._connect() as db:
            side = db.execute("SELECT 1 FROM conversations WHERE id = ? AND kind = 'side' AND merged_into IS NULL", (chat_id,)).fetchone()
            if side is None:
                return False
            master_id = db.execute("SELECT id FROM conversations WHERE is_master = 1").fetchone()[0]
            db.execute("UPDATE conversation_messages SET conversation_id = ? WHERE conversation_id = ?", (master_id, chat_id))
            db.execute("UPDATE conversations SET merged_into = ? WHERE id = ?", (master_id, chat_id))
            db.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (master_id,))
            db.execute("INSERT INTO audit_log(action, target, approved, allowed, reason) VALUES ('move_side_to_master', ?, 1, 1, 'Explicit user action; original conversation preserved')", (str(chat_id),))
        return True

    def delete_conversation(self, chat_id: int, approved=False) -> bool:
        """Delete only one Jarvis chat and its dependent rows, never a file or general memory."""
        self._require_approval(approved)
        with self._connect() as db:
            row = db.execute("SELECT is_master, merged_into FROM conversations WHERE id = ?", (chat_id,)).fetchone()
            if row and (row[0] or row[1] is not None):
                raise PermissionError("Master Chat and preserved archives cannot be deleted.")
            result = db.execute("DELETE FROM conversations WHERE id = ? AND kind = 'side'", (chat_id,))
            if result.rowcount:
                db.execute(
                    "INSERT INTO audit_log (action, target, approved, allowed, reason, "
                    "authorization_source, security_result, execution_result) "
                    "VALUES ('delete_conversation', ?, 1, 1, 'User-confirmed Jarvis chat deletion', "
                    "'user_confirmed', 'chat_scope_only', 'deleted')",
                    (str(chat_id),),
                )
        return result.rowcount > 0

    def has_permission(self, action_type: str, target: str) -> bool:
        with self._connect(readonly=True) as db:
            row = db.execute(
                "SELECT 1 FROM permissions WHERE action_type = ? AND target = ? AND decision = 'allow'",
                (action_type, target),
            ).fetchone()
        return row is not None

    def list_permissions(self) -> list[dict]:
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT id, action_type, target, decision, created_at, updated_at "
                "FROM permissions ORDER BY action_type, target"
            ).fetchall()
        return [dict(row) for row in rows]

    def grant_permission(self, action_type: str, target: str, approved: bool = False, safety_epoch=None) -> None:
        self._require_approval(approved)
        import safety as safety_runtime
        if safety_epoch is not None: safety_runtime.safety.ensure_running(safety_epoch)
        with self._connect() as db:
            if safety_epoch is not None: safety_runtime.safety.ensure_running(safety_epoch)
            db.execute(
                "INSERT INTO permissions (action_type, target, decision) VALUES (?, ?, 'allow') "
                "ON CONFLICT(action_type, target) DO UPDATE SET "
                "decision = 'allow', updated_at = CURRENT_TIMESTAMP",
                (action_type, target),
            )
            # Raising here rolls the existing transaction back if Stop raced
            # the database write. Resume cannot revive its original approval.
            if safety_epoch is not None: safety_runtime.safety.ensure_running(safety_epoch)

    def revoke_permission(self, permission_id: int, approved: bool = False) -> bool:
        self._require_approval(approved)
        with self._connect() as db:
            result = db.execute("DELETE FROM permissions WHERE id = ?", (permission_id,))
        return result.rowcount > 0

    def add_memory(self, kind, content, source=None, approved=False):
        self._require_approval(approved)

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memories (kind, content, source)
                VALUES (?, ?, ?)
                """,
                (kind, content, source),
            )

    def commit_side_memory(self, chat_id, approved=False):
        """Explicitly copy side exchanges to recall without moving their history."""
        self._require_approval(approved)
        with self._connect() as db:
            side = db.execute("SELECT kind,is_master,merged_into FROM conversations WHERE id=?", (chat_id,)).fetchone()
            if side is None or side[0] != "side" or side[1] or side[2] is not None:
                raise ValueError("Side chat not found.")
            messages = db.execute("SELECT id,role,content FROM conversation_messages WHERE conversation_id=? ORDER BY id", (chat_id,)).fetchall()
            saved = 0
            pending = None
            for message_id, role, content in messages:
                if role == "user":
                    pending = content
                elif role == "assistant" and pending is not None:
                    source = f"explicit-side-commit:{chat_id}:{message_id}"
                    inserted = db.execute("INSERT INTO memories(kind,content,source) SELECT ?,?,? WHERE NOT EXISTS (SELECT 1 FROM memories WHERE source=?)", ("conversation", "User: " + pending + "\nJarvis: " + content, source, source))
                    saved += inserted.rowcount
                    pending = None
        self.log_action("commit_side_memory", str(chat_id), True, True, "Explicit user memory commit", write_approved=True)
        return saved

    def search_memories(self, query, limit=10):
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT id, kind, content, source, created_at
                FROM memories
                WHERE content LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()

        return [dict(row) for row in rows]

    def set_fact(self, key, value, source="user", approved=False):
        self._require_approval(approved)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError("Fact key and value are required.")

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO facts (key, value, source)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value, source),
            )
            db.execute(
                """
                INSERT INTO audit_log (action, target, approved, allowed, reason)
                VALUES ('set_fact', ?, 1, 1, 'User-approved fact save')
                """,
                (key,),
            )

    def save_stated_fact(self, key, value, source="user-stated", approved=False):
        """Store or correct a directly stated fact under the user's standing approval."""
        self._require_approval(approved)
        key = key.strip().lower()
        value = value.strip()
        if not key or not value:
            raise ValueError("Fact key and value are required.")
        with self._connect() as db:
            existing = db.execute(
                "SELECT key, value FROM facts WHERE key = ? COLLATE NOCASE", (key,)
            ).fetchone()
            if existing is not None and existing[1] == value:
                return False
            if existing is None:
                db.execute(
                    "INSERT INTO facts (key, value, source) VALUES (?, ?, ?)",
                    (key, value, source),
                )
                action = "auto_save_fact"
            else:
                db.execute(
                    "UPDATE facts SET value = ?, source = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                    (value, source, existing[0]),
                )
                action = "auto_update_fact"
            db.execute(
                "INSERT INTO audit_log (action, target, approved, allowed, reason) "
                "VALUES (?, ?, 1, 1, 'Standing approval for stable user-stated facts')",
                (action, key),
            )
        return True

    def list_facts(self, limit=100):
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT key, value, source, updated_at
                FROM facts
                ORDER BY updated_at DESC, key
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def add_message(self, role, content, approved=False):
        self._require_approval(approved)

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO messages (role, content)
                VALUES (?, ?)
                """,
                (role, content),
            )

    def add_exchange(self, user_text, assistant_text, approved=False):
        self._require_approval(approved)

        with self._connect() as db:
            db.executemany(
                "INSERT INTO messages (role, content) VALUES (?, ?)",
                (("user", user_text), ("assistant", assistant_text)),
            )
            db.execute(
                """
                INSERT INTO audit_log (action, target, approved, allowed, reason)
                VALUES ('save_exchange', 'messages', 1, 1, 'User-approved exchange save')
                """
            )

    def recent_messages(self, limit=20):
        with self._connect(readonly=True) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT role, content, created_at
                FROM messages
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in reversed(rows)]

    def set_preference(self, key, value, approved=False):
        self._require_approval(approved)

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO preferences (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )

    def get_preference(self, key):
        with self._connect(readonly=True) as db:
            row = db.execute(
                "SELECT value FROM preferences WHERE key = ?",
                (key,),
            ).fetchone()

        return row[0] if row else None

    def set_project_state(self, key, value, approved=False):
        self._require_approval(approved)

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO project_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )

    def get_project_state(self, key):
        with self._connect(readonly=True) as db:
            row = db.execute(
                "SELECT value FROM project_state WHERE key = ?",
                (key,),
            ).fetchone()

        return row[0] if row else None

    def log_action(
        self,
        action,
        target,
        approved,
        allowed,
        reason="",
        write_approved=False,
        authorization_source=None,
        security_result=None,
        execution_result=None,
        latency_ms=None,
    ):
        self._require_approval(write_approved)

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO audit_log
                (action, target, approved, allowed, reason,
                 authorization_source, security_result, execution_result, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    target,
                    int(approved),
                    int(allowed),
                    reason,
                    authorization_source,
                    security_result,
                    execution_result,
                    latency_ms,
                ),
            )

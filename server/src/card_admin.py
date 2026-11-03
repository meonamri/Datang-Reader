"""
RFID card management screen: GET /cards (page) + /cards/api/* (JSON).

Lets the office:
  - see which cards were tapped but are not known (unknown / retired),
  - find a card, a student or a whole class,
  - assign a card to a roster student or to a student who is not in any IDME
    roster (classes with no IDME teacher), replacing their previous card,
  - retire a lost card so the reader refuses it,
  - see every change made here (card_audit).

Rules:
  - A student has at most one active card. Assigning a new one retires the
    previous card(s), so a lost card that turns up cannot check them in.
  - A card belongs to at most one student. Moving a card that someone else
    holds needs an explicit `force` (the UI asks first).
  - Roster tags set here get tag_source='admin', which Datang.my name-matching
    in ScanTracker._learn_tag will not overwrite.

Access: same as the existing /idme/settings screen (private tailnet only;
never publish it through a public proxy). POSTs need the
X-Requested-With: cards-ui header so another site cannot drive them from a
logged-in browser. The actor recorded is the Tailscale Serve login header when
present, else the name typed in the page, else the client IP.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, Response, jsonify, request

from .local_attendance import LocalAttendanceStore

CARD_RE = re.compile(r"^\d{10}$")


class CardConflict(Exception):
    def __init__(self, holder: Dict[str, Any]):
        super().__init__("card already assigned")
        self.holder = holder


def _who(name: Optional[str], cls: Optional[str]) -> Optional[str]:
    return f"{name} ({cls})" if name else None


class CardAdmin:
    def __init__(self, store: LocalAttendanceStore):
        self.store = store

    def _conn(self) -> sqlite3.Connection:
        return self.store._conn()

    # ------------------------------------------------------------ reads
    def summary(self) -> Dict[str, Any]:
        conn = self._conn()
        try:
            one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
            return {
                "mode": self.store.mode,
                "roster_students": one("SELECT COUNT(*) FROM students WHERE enabled = 1"),
                "roster_with_card": one("SELECT COUNT(*) FROM students WHERE enabled = 1 AND integration_tag IS NOT NULL"),
                "directory_only": one(
                    "SELECT COUNT(*) FROM card_directory d WHERE retired = 0 AND NOT EXISTS "
                    "(SELECT 1 FROM students s WHERE s.enabled = 1 AND s.integration_tag = d.card_id)"),
                "retired": one("SELECT COUNT(*) FROM card_directory WHERE retired = 1"),
                "unknown_cards_14d": len(self.unknown(14)),
            }
        finally:
            conn.close()

    def classes(self) -> List[str]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT class_name FROM students WHERE enabled = 1 UNION "
                "SELECT class_name FROM card_directory WHERE retired = 0").fetchall()
        finally:
            conn.close()
        return sorted({r[0] for r in rows if r[0]})

    def unknown(self, days: int = 14) -> List[Dict[str, Any]]:
        since = (datetime.now() - timedelta(days=days)).date().isoformat()
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT card_id, COUNT(*) AS taps, MIN(scanned_at) AS first_tap,
                          MAX(scanned_at) AS last_tap, GROUP_CONCAT(DISTINCT reader_id) AS readers,
                          MAX(status) AS status, MAX(datang_name) AS datang_name,
                          MAX(datang_class) AS datang_class
                   FROM attendance_events
                   WHERE scan_date >= ? AND status IN ('unknown_card', 'retired_card', 'datang_rejected')
                   GROUP BY card_id ORDER BY last_tap DESC LIMIT 300""",
                (since,)).fetchall()
            out = []
            for r in rows:
                who = self.store.resolve(r["card_id"], conn)
                # a card assigned since its last unknown tap is no longer a problem
                if who and not who.get("retired"):
                    continue
                d = dict(r)
                d["retired_holder"] = _who(who["name"], who["class_name"]) if who else None
                out.append(d)
            return out
        finally:
            conn.close()

    def _last_seen(self, conn, card_id: Optional[str]) -> Optional[str]:
        if not card_id:
            return None
        return conn.execute("SELECT MAX(scan_time) FROM daily_scans WHERE integration_tag = ?",
                            (card_id,)).fetchone()[0]

    def search(self, q: str) -> List[Dict[str, Any]]:
        q = (q or "").strip()
        if not q:
            return []
        conn = self._conn()
        try:
            people: List[Dict[str, Any]] = []
            if q.isdigit():
                roster = conn.execute(
                    "SELECT id, name, class_name, integration_tag, tag_source FROM students "
                    "WHERE enabled = 1 AND integration_tag LIKE ? LIMIT 50", (q + "%",)).fetchall()
                directory = conn.execute(
                    "SELECT * FROM card_directory WHERE card_id LIKE ? LIMIT 50", (q + "%",)).fetchall()
            else:
                exact_class = conn.execute(
                    "SELECT 1 FROM students WHERE enabled = 1 AND class_name = ? UNION "
                    "SELECT 1 FROM card_directory WHERE class_name = ? LIMIT 1", (q, q)).fetchone()
                if exact_class:
                    roster = conn.execute(
                        "SELECT id, name, class_name, integration_tag, tag_source FROM students "
                        "WHERE enabled = 1 AND class_name = ? ORDER BY name", (q,)).fetchall()
                    directory = conn.execute(
                        "SELECT * FROM card_directory WHERE class_name = ? ORDER BY student_name", (q,)).fetchall()
                else:
                    like = f"%{q.upper()}%"
                    roster = conn.execute(
                        "SELECT id, name, class_name, integration_tag, tag_source FROM students "
                        "WHERE enabled = 1 AND UPPER(name) LIKE ? ORDER BY name LIMIT 50", (like,)).fetchall()
                    directory = conn.execute(
                        "SELECT * FROM card_directory WHERE UPPER(student_name) LIKE ? "
                        "ORDER BY student_name LIMIT 50", (like,)).fetchall()
            roster_cards = set()
            for r in roster:
                roster_cards.add(r["integration_tag"])
                people.append({"kind": "roster", "student_id": r["id"], "name": r["name"],
                               "class_name": r["class_name"], "card_id": r["integration_tag"],
                               "card_source": r["tag_source"], "retired": False,
                               "last_seen": self._last_seen(conn, r["integration_tag"])})
            for d in directory:
                if d["card_id"] in roster_cards and not d["retired"]:
                    continue        # same card already shown on its roster row
                people.append({"kind": "directory", "student_id": None, "name": d["student_name"],
                               "class_name": d["class_name"], "card_id": d["card_id"],
                               "card_source": d["source"], "retired": bool(d["retired"]),
                               "last_seen": self._last_seen(conn, d["card_id"])})
            return people
        finally:
            conn.close()

    def students_without_card(self) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT id AS student_id, name, class_name FROM students "
                "WHERE enabled = 1 AND (integration_tag IS NULL OR integration_tag = '') "
                "ORDER BY class_name, name").fetchall()]
        finally:
            conn.close()

    def audit(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM card_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        finally:
            conn.close()

    # ----------------------------------------------------------- writes
    def assign(self, card_id: str, *, student_id: Optional[int] = None,
               name: Optional[str] = None, class_name: Optional[str] = None,
               force: bool = False, actor: str = "", note: str = "") -> Dict[str, Any]:
        card_id = (card_id or "").strip()
        if not CARD_RE.match(card_id):
            raise ValueError("Card number must be exactly 10 digits")
        now = datetime.now().isoformat()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if student_id is not None:
                st = conn.execute("SELECT id, name, class_name, integration_tag FROM students "
                                  "WHERE id = ? AND enabled = 1", (student_id,)).fetchone()
                if st is None:
                    raise ValueError("Student not found in the roster")
                t_name, t_class = st["name"].strip().upper(), st["class_name"]
            else:
                t_name = (name or "").strip().upper()
                t_class = (class_name or "").strip()
                if not t_name or not t_class:
                    raise ValueError("Name and class are required for a student not in the roster")
                st = None

            # Who holds this card now?
            holder = self.store.resolve(card_id, conn)
            old_holder = _who(holder["name"], holder["class_name"]) if holder else None
            same_person = holder and not holder.get("retired") and \
                holder["name"] == t_name and holder["class_name"] == t_class
            if holder and not holder.get("retired") and not same_person and not force:
                raise CardConflict({"name": holder["name"], "class_name": holder["class_name"],
                                    "via": holder["via"]})

            # Take the card away from any other roster student
            conn.execute("UPDATE students SET integration_tag = NULL, tag_source = 'admin', tag_updated_at = ? "
                         "WHERE integration_tag = ? AND enabled = 1 AND id IS NOT ?",
                         (now, card_id, st["id"] if st else None))

            # Retire this student's previous card(s): one active card per student
            previous = set()
            if st is not None and st["integration_tag"] and st["integration_tag"] != card_id:
                previous.add(st["integration_tag"])
            previous.update(r[0] for r in conn.execute(
                "SELECT card_id FROM card_directory WHERE student_name = ? AND class_name = ? "
                "AND retired = 0 AND card_id != ?", (t_name, t_class, card_id)).fetchall())
            for old in previous:
                conn.execute(
                    """INSERT INTO card_directory (card_id, student_name, class_name, source, retired,
                                                  first_seen, last_seen, updated_at)
                       VALUES (?, ?, ?, 'admin', 1, ?, ?, ?)
                       ON CONFLICT(card_id) DO UPDATE SET retired = 1, source = 'admin',
                                                          updated_at = excluded.updated_at""",
                    (old, t_name, t_class, now, now, now))
                self._audit(conn, "retire", old, _who(t_name, t_class), None, actor,
                            f"replaced by {card_id}" + (f"; {note}" if note else ""))

            if st is not None:
                conn.execute("UPDATE students SET integration_tag = ?, tag_source = 'admin', tag_updated_at = ? "
                             "WHERE id = ?", (card_id, now, st["id"]))
            conn.execute(
                """INSERT INTO card_directory (card_id, student_name, class_name, source, retired,
                                              first_seen, last_seen, updated_at)
                   VALUES (?, ?, ?, 'admin', 0, ?, ?, ?)
                   ON CONFLICT(card_id) DO UPDATE SET student_name = excluded.student_name,
                       class_name = excluded.class_name, source = 'admin', retired = 0,
                       updated_at = excluded.updated_at""",
                (card_id, t_name, t_class, now, now, now))
            conn.execute("UPDATE unmatched_scans SET resolved = 1 WHERE card_id = ?", (card_id,))
            self._audit(conn, "assign", card_id, old_holder, _who(t_name, t_class), actor, note)
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
        return {"card_id": card_id, "holder": _who(t_name, t_class),
                "previous_holder": old_holder, "retired_previous": sorted(previous)}

    def retire(self, card_id: str, *, actor: str = "", note: str = "") -> Dict[str, Any]:
        card_id = (card_id or "").strip()
        if not CARD_RE.match(card_id):
            raise ValueError("Card number must be exactly 10 digits")
        now = datetime.now().isoformat()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            holder = self.store.resolve(card_id, conn)
            name = holder["name"] if holder else ""
            cls = holder["class_name"] if holder else ""
            conn.execute("UPDATE students SET integration_tag = NULL, tag_source = 'admin', tag_updated_at = ? "
                         "WHERE integration_tag = ?", (now, card_id))
            conn.execute(
                """INSERT INTO card_directory (card_id, student_name, class_name, source, retired,
                                              first_seen, last_seen, updated_at)
                   VALUES (?, ?, ?, 'admin', 1, ?, ?, ?)
                   ON CONFLICT(card_id) DO UPDATE SET retired = 1, source = 'admin',
                                                      updated_at = excluded.updated_at""",
                (card_id, name, cls, now, now, now))
            self._audit(conn, "retire", card_id, _who(name, cls), None, actor, note)
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
        return {"card_id": card_id, "previous_holder": _who(name, cls)}

    @staticmethod
    def _audit(conn, action, card_id, old, new, actor, note):
        conn.execute("INSERT INTO card_audit (at, action, card_id, old_holder, new_holder, actor, note) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (datetime.now().isoformat(timespec="seconds"), action, card_id, old, new,
                      (actor or "")[:120] or None, (note or "")[:300] or None))


# ====================================================================== web
def create_cards_blueprint(get_store) -> Blueprint:
    """`get_store()` returns the LocalAttendanceStore (constructed lazily in
    'datang' mode, where it is used only as the card registry)."""
    bp = Blueprint("cards", __name__)
    template = Path(__file__).parent / "templates" / "cards.html"

    def admin() -> CardAdmin:
        return CardAdmin(get_store())

    def actor() -> str:
        login = request.headers.get("Tailscale-User-Login")
        typed = (request.get_json(silent=True) or {}).get("by", "")
        parts = [p for p in (login, str(typed).strip()) if p]
        return " / ".join(parts) or (request.remote_addr or "unknown")

    @bp.before_request
    def csrf_guard():
        if request.method == "POST" and request.headers.get("X-Requested-With") != "cards-ui":
            return jsonify({"error": "missing X-Requested-With header"}), 403

    @bp.route("/cards", methods=["GET"])
    def page():
        # Served as-is (not through Jinja): the page is static HTML + JS.
        return Response(template.read_text(), mimetype="text/html")

    @bp.route("/cards/api/summary")
    def api_summary():
        a = admin()
        return jsonify({**a.summary(), "classes": a.classes()})

    @bp.route("/cards/api/unknown")
    def api_unknown():
        days = min(max(int(request.args.get("days", 14)), 1), 60)
        return jsonify({"days": days, "cards": admin().unknown(days)})

    @bp.route("/cards/api/search")
    def api_search():
        return jsonify({"results": admin().search(request.args.get("q", ""))})

    @bp.route("/cards/api/without-card")
    def api_without():
        return jsonify({"students": admin().students_without_card()})

    @bp.route("/cards/api/audit")
    def api_audit():
        return jsonify({"changes": admin().audit()})

    @bp.route("/cards/api/assign", methods=["POST"])
    def api_assign():
        body = request.get_json(silent=True) or {}
        try:
            sid = body.get("student_id")
            result = admin().assign(
                str(body.get("card_id", "")),
                student_id=int(sid) if sid not in (None, "") else None,
                name=body.get("name"), class_name=body.get("class_name"),
                force=bool(body.get("force")), actor=actor(), note=str(body.get("note", "")))
            return jsonify({"ok": True, **result})
        except CardConflict as c:
            return jsonify({"ok": False, "conflict": c.holder,
                            "error": f"Card belongs to {c.holder['name']} ({c.holder['class_name']})"}), 409
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @bp.route("/cards/api/retire", methods=["POST"])
    def api_retire():
        body = request.get_json(silent=True) or {}
        try:
            return jsonify({"ok": True, **admin().retire(str(body.get("card_id", "")), actor=actor(),
                                                        note=str(body.get("note", "")))})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    return bp

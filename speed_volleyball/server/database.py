import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "players.db"

DEFAULT_LEAGUES = ["Presbytery", "DCC"]


def _conn():
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = _conn()

    c.execute("""CREATE TABLE IF NOT EXISTS Player (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        rating REAL NOT NULL,
        created_at TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS League (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )""")

    # Per-league ratings — seeded from Player.rating when a player first joins a league
    c.execute("""CREATE TABLE IF NOT EXISTS LeagueRating (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        league_id INTEGER NOT NULL,
        rating REAL NOT NULL,
        UNIQUE(player_id, league_id),
        FOREIGN KEY (player_id) REFERENCES Player(id),
        FOREIGN KEY (league_id) REFERENCES League(id)
    )""")

    # Migrate old RatingHistory (no league_id) to new schema
    rh_cols = [row[1] for row in c.execute("PRAGMA table_info(RatingHistory)").fetchall()]
    if rh_cols and "league_id" not in rh_cols:
        c.execute("DROP TABLE RatingHistory")
        c.commit()

    c.execute("""CREATE TABLE IF NOT EXISTS RatingHistory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        league_id INTEGER NOT NULL,
        old_rating REAL NOT NULL,
        new_rating REAL NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (player_id) REFERENCES Player(id),
        FOREIGN KEY (league_id) REFERENCES League(id)
    )""")

    # Migrate old SignUp (no league_id) to new schema
    su_cols = [row[1] for row in c.execute("PRAGMA table_info(SignUp)").fetchall()]
    if su_cols and "league_id" not in su_cols:
        c.execute("DROP TABLE SignUp")
        c.commit()

    c.execute("""CREATE TABLE IF NOT EXISTS SignUp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        league_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        UNIQUE(player_id, league_id),
        FOREIGN KEY (player_id) REFERENCES Player(id),
        FOREIGN KEY (league_id) REFERENCES League(id)
    )""")

    for name in DEFAULT_LEAGUES:
        c.execute("INSERT OR IGNORE INTO League (name) VALUES (?)", (name,))

    c.execute("""CREATE TABLE IF NOT EXISTS Meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    # One-time migration: ratings used to be stored on the 1-10 frontend scale;
    # the backend now stores them on a 1-1000 scale (RATING_SCALE in config.py).
    if not c.execute("SELECT 1 FROM Meta WHERE key='rating_scale_v2'").fetchone():
        c.execute("UPDATE Player SET rating = rating * 100")
        c.execute("UPDATE LeagueRating SET rating = rating * 100")
        c.execute("UPDATE RatingHistory SET old_rating = old_rating * 100, new_rating = new_rating * 100")
        c.execute("INSERT INTO Meta (key, value) VALUES ('rating_scale_v2', '1')")

    c.commit()
    c.close()


# ── Internal helpers ───────────────────────────────────────────────────────────

def _ensure_league_rating(c, player_id: int, league_id: int):
    """Seed a LeagueRating row from Player.rating if one doesn't exist yet."""
    row = c.execute(
        "SELECT 1 FROM LeagueRating WHERE player_id=? AND league_id=?", (player_id, league_id)
    ).fetchone()
    if not row:
        seed = c.execute("SELECT rating FROM Player WHERE id=?", (player_id,)).fetchone()
        if seed:
            c.execute(
                "INSERT OR IGNORE INTO LeagueRating (player_id, league_id, rating) VALUES (?,?,?)",
                (player_id, league_id, seed["rating"]),
            )


# ── Leagues ────────────────────────────────────────────────────────────────────

def get_leagues():
    c = _conn()
    rows = c.execute("SELECT * FROM League ORDER BY id").fetchall()
    c.close()
    return [dict(r) for r in rows]


def add_league(name: str) -> dict:
    c = _conn()
    cur = c.execute("INSERT INTO League (name) VALUES (?)", (name,))
    c.commit()
    row = c.execute("SELECT * FROM League WHERE id=?", (cur.lastrowid,)).fetchone()
    c.close()
    return dict(row)


def get_league(league_id: int):
    c = _conn()
    row = c.execute("SELECT * FROM League WHERE id=?", (league_id,)).fetchone()
    c.close()
    return dict(row) if row else None


# ── Players (global — seed ratings only) ──────────────────────────────────────

def get_all_players():
    """All players with their seed ratings. Used for new-player lookup in kiosk."""
    c = _conn()
    rows = c.execute("SELECT * FROM Player ORDER BY rating DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def add_new_player(name: str, rating: float) -> dict:
    c = _conn()
    now = datetime.utcnow().isoformat()
    cur = c.execute(
        "INSERT INTO Player (name, rating, created_at) VALUES (?,?,?)", (name, rating, now)
    )
    c.commit()
    row = c.execute("SELECT * FROM Player WHERE id=?", (cur.lastrowid,)).fetchone()
    c.close()
    return dict(row)


def update_player_name(player_id: int, name: str):
    """Update a player's name globally."""
    c = _conn()
    c.execute("UPDATE Player SET name=? WHERE id=?", (name, player_id))
    c.commit()
    c.close()


# ── Players (league-scoped — live ratings) ─────────────────────────────────────

def get_all_players_for_league(league_id: int):
    """All players with their league-specific ratings (falls back to seed rating)."""
    c = _conn()
    rows = c.execute(
        """SELECT p.id, p.name, COALESCE(lr.rating, p.rating) AS rating, p.created_at
           FROM Player p
           LEFT JOIN LeagueRating lr ON p.id=lr.player_id AND lr.league_id=?
           ORDER BY COALESCE(lr.rating, p.rating) DESC""",
        (league_id,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def update_league_rating(player_id: int, league_id: int, new_rating: float):
    c = _conn()
    row = c.execute(
        "SELECT rating FROM LeagueRating WHERE player_id=? AND league_id=?", (player_id, league_id)
    ).fetchone()
    if row:
        old_rating = row["rating"]
        now = datetime.utcnow().isoformat()
        c.execute(
            "UPDATE LeagueRating SET rating=? WHERE player_id=? AND league_id=?",
            (new_rating, player_id, league_id),
        )
        c.execute(
            "INSERT INTO RatingHistory (player_id, league_id, old_rating, new_rating, timestamp) VALUES (?,?,?,?,?)",
            (player_id, league_id, old_rating, new_rating, now),
        )
        c.commit()
    c.close()


def update_player_for_league(player_id: int, league_id: int, name: str = None, rating: float = None):
    """Edit a player's name (global) and/or their rating for a specific league."""
    c = _conn()
    now = datetime.utcnow().isoformat()
    if name is not None:
        c.execute("UPDATE Player SET name=? WHERE id=?", (name, player_id))
    if rating is not None:
        row = c.execute(
            "SELECT rating FROM LeagueRating WHERE player_id=? AND league_id=?", (player_id, league_id)
        ).fetchone()
        if row:
            old_rating = row["rating"]
            c.execute(
                "UPDATE LeagueRating SET rating=? WHERE player_id=? AND league_id=?",
                (rating, player_id, league_id),
            )
            c.execute(
                "INSERT INTO RatingHistory (player_id, league_id, old_rating, new_rating, timestamp) VALUES (?,?,?,?,?)",
                (player_id, league_id, old_rating, rating, now),
            )
        else:
            c.execute(
                "INSERT INTO LeagueRating (player_id, league_id, rating) VALUES (?,?,?)",
                (player_id, league_id, rating),
            )
    c.commit()
    row = c.execute(
        """SELECT p.id, p.name, COALESCE(lr.rating, p.rating) AS rating, p.created_at
           FROM Player p
           LEFT JOIN LeagueRating lr ON p.id=lr.player_id AND lr.league_id=?
           WHERE p.id=?""",
        (league_id, player_id),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def get_league_rating_history(player_id: int, league_id: int):
    c = _conn()
    rows = c.execute(
        "SELECT * FROM RatingHistory WHERE player_id=? AND league_id=? ORDER BY timestamp DESC",
        (player_id, league_id),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ── Sign-ups (league-scoped) ───────────────────────────────────────────────────

def get_signed_up_players(league_id: int):
    """Signed-up players with their league-specific ratings."""
    c = _conn()
    rows = c.execute(
        """SELECT p.id, p.name, COALESCE(lr.rating, p.rating) AS rating, p.created_at
           FROM Player p
           JOIN SignUp s ON p.id=s.player_id
           LEFT JOIN LeagueRating lr ON p.id=lr.player_id AND lr.league_id=?
           WHERE s.league_id=?
           ORDER BY s.timestamp ASC""",
        (league_id, league_id),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def sign_up_player(player_id: int, league_id: int) -> bool:
    c = _conn()
    try:
        _ensure_league_rating(c, player_id, league_id)
        now = datetime.utcnow().isoformat()
        c.execute(
            "INSERT INTO SignUp (player_id, league_id, timestamp) VALUES (?,?,?)",
            (player_id, league_id, now),
        )
        c.commit()
        c.close()
        return True
    except sqlite3.IntegrityError:
        c.close()
        return False


def clear_signups(league_id: int):
    c = _conn()
    c.execute("DELETE FROM SignUp WHERE league_id=?", (league_id,))
    c.commit()
    c.close()

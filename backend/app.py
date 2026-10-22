import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import time
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from backend import game_engine


# Monetary values are arbitrary precision. HTTP request sizes remain capped below.
if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)

BASE_DIR = Path(__file__).resolve().parent.parent
USERNAME_PATTERN = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]{3,24}\Z")
EMAIL_PATTERN = re.compile(r"[^@\s]{1,64}@[^@\s]{1,255}\Z")
SESSION_LIFETIME = 60 * 60 * 24 * 30
SESSION_COOKIE = "beton_session"
MONEY_FIELDS = ("wallet_balance", "total_wagered", "total_won", "biggest_win")


def parse_money(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        return int(value)
    raise ValueError("Invalid amount")


def money_json(value):
    return value if value <= 9_007_199_254_740_991 else str(value)


def player_row(cursor, values):
    row = dict(zip((column[0] for column in cursor.description), values))
    for field in MONEY_FIELDS:
        if field + "_exact" in row:
            row[field] = int(row[field + "_exact"])
    return row
GAME_IDS = {"slots", "blackjack", "roulette", "crash", "dice", "mines", "coinflip", "highlow", "cups", "poker"}
def create_app(test_config=None):
    app = Flask(__name__, static_folder=None)
    instance_dir = BASE_DIR / "instance"
    app.config.from_mapping(
        DATABASE=os.environ.get("BETON_DATABASE", str(instance_dir / "beton.sqlite3")),
        COOKIE_SECURE=os.environ.get("BETON_COOKIE_SECURE", "false").lower() == "true",
        PUBLIC_ORIGIN=os.environ.get("BETON_PUBLIC_ORIGIN", "").rstrip("/"),
        BEHIND_PROXY=os.environ.get("BETON_BEHIND_PROXY", "false").lower() == "true",
        MAX_CONTENT_LENGTH=128 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    database_path = Path(app.config["DATABASE"])
    database_path.parent.mkdir(parents=True, exist_ok=True)

    if app.config["BEHIND_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(database_path, timeout=15)
            g.db.row_factory = player_row
            g.db.execute("PRAGMA foreign_keys = ON")
            g.db.execute("PRAGMA busy_timeout = 15000")
        return g.db

    def close_db(_error=None):
        database = g.pop("db", None)
        if database is not None:
            database.close()

    def init_db():
        database = get_db()
        database.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                total_won INTEGER NOT NULL DEFAULT 0 CHECK (total_won >= 0),
                biggest_win INTEGER NOT NULL DEFAULT 0 CHECK (biggest_win >= 0),
                plays INTEGER NOT NULL DEFAULT 0 CHECK (plays >= 0),
                created_at INTEGER NOT NULL,
                game_state TEXT,
                wallet_balance INTEGER NOT NULL DEFAULT 5000 CHECK (wallet_balance >= 0 AND wallet_balance <= 9007199254740991),
                total_wagered INTEGER NOT NULL DEFAULT 0 CHECK (total_wagered >= 0),
                wins INTEGER NOT NULL DEFAULT 0 CHECK (wins >= 0),
                purchases INTEGER NOT NULL DEFAULT 0 CHECK (purchases >= 0),
                progress_state TEXT NOT NULL DEFAULT '{}',
                active_round TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
            """
        )
        database.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)"
        )
        player_columns = {row["name"] for row in database.execute("PRAGMA table_info(players)")}
        if "game_state" not in player_columns:
            database.execute("ALTER TABLE players ADD COLUMN game_state TEXT")
        if "wallet_balance" not in player_columns:
            database.execute("ALTER TABLE players ADD COLUMN wallet_balance INTEGER NOT NULL DEFAULT 5000")
        if "total_wagered" not in player_columns:
            database.execute("ALTER TABLE players ADD COLUMN total_wagered INTEGER NOT NULL DEFAULT 0")
        if "wins" not in player_columns:
            database.execute("ALTER TABLE players ADD COLUMN wins INTEGER NOT NULL DEFAULT 0")
        if "purchases" not in player_columns:
            database.execute("ALTER TABLE players ADD COLUMN purchases INTEGER NOT NULL DEFAULT 0")
        if "progress_state" not in player_columns:
            database.execute("ALTER TABLE players ADD COLUMN progress_state TEXT NOT NULL DEFAULT '{}'")
        if "active_round" not in player_columns:
            database.execute("ALTER TABLE players ADD COLUMN active_round TEXT")
        for field in MONEY_FIELDS:
            # Identifiers are from a fixed internal tuple, never user input.
            if field + "_exact" not in player_columns:
                default = "5000" if field == "wallet_balance" else "0"
                database.execute(f"ALTER TABLE players ADD COLUMN {field}_exact TEXT NOT NULL DEFAULT '{default}'")
                database.execute(f"UPDATE players SET {field}_exact = CAST({field} AS TEXT)")
        database.commit()

    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

    def valid_bet(value):
        try:
            return parse_money(value) >= 50 and parse_money(value) % 50 == 0
        except ValueError:
            return False

    def serialize_outcome(outcome):
        return {**outcome, "payout": money_json(outcome["payout"]), "won": money_json(outcome["won"])} if outcome else None

    def settle_wallet(database, player, balance, wager, won, active, play=False):
        database.execute(
            """UPDATE players SET wallet_balance_exact = ?, total_wagered_exact = ?,
               total_won_exact = ?, biggest_win_exact = ?, plays = plays + ?,
               wins = wins + ?, active_round = ? WHERE id = ?""",
            (str(balance), str(player["total_wagered"] + wager),
             str(player["total_won"] + won), str(max(player["biggest_win"], won)),
             int(play), int(won > 0), json.dumps(active, separators=(",", ":")) if active else None, player["id"]),
        )

    def player_json(player):
        return {
            "id": player["id"],
            "email": player["email"],
            "username": player["username"],
            "total_won": money_json(player["total_won"]),
            "biggest_win": money_json(player["biggest_win"]),
            "plays": player["plays"],
            "balance": money_json(player["wallet_balance"]),
            "total_wagered": money_json(player["total_wagered"]),
            "wins": player["wins"],
            "purchases": player["purchases"],
        }

    def game_state_for(player):
        try:
            progress = json.loads(player["progress_state"] or "{}")
        except (TypeError, json.JSONDecodeError):
            progress = {}
        try:
            preferences = json.loads(player["game_state"] or "{}")
        except (TypeError, json.JSONDecodeError):
            preferences = {}
        state = {
            "balance": money_json(player["wallet_balance"]),
            "owned": progress.get("owned", []),
            "reputation": progress.get("reputation", 0),
            "claimed": progress.get("claimed", []),
            "storySeen": progress.get("storySeen", []),
            "storyFlags": progress.get("storyFlags", {}),
            "lastRefill": progress.get("lastRefill", 0),
            "sound": preferences.get("sound", True),
            "bets": preferences.get("bets", {}),
            "stats": {
                "wagered": money_json(player["total_wagered"]),
                "won": money_json(player["total_won"]),
                "biggest": money_json(player["biggest_win"]),
                "plays": player["plays"],
                "wins": player["wins"],
                "purchases": player["purchases"],
            },
        }
        return state

    def get_perks(player):
        try:
            progress = json.loads(player["progress_state"] or "{}")
        except (TypeError, json.JSONDecodeError):
            progress = {}
        owned = set(progress.get("owned", []))
        flags = progress.get("storyFlags", {})
        return {item: item in owned for item in ("slot_token", "bj_course", "wheel_contact", "risk_protocol", "calibrated_dice", "counting_ledger", "cup_magnet", "poker_atlas") } | {
            "bold": bool(flags.get("bold")),
            "hiredMax": bool(flags.get("hiredMax")),
            "capitalDeal": bool(flags.get("capitalDeal")),
            "publicChallenge": bool(flags.get("publicChallenge")),
            "protectedDistrict": bool(flags.get("protectedDistrict")),
            "trustedGrom": bool(flags.get("trustedGrom")),
            "choseConnections": bool(flags.get("choseConnections")),
        }

    def json_error(message, status):
        return jsonify({"error": message}), status

    def request_json():
        if not request.is_json:
            return None
        payload = request.get_json(silent=True)
        return payload if isinstance(payload, dict) else None

    def origin_is_allowed():
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        origin = request.headers.get("Origin")
        if not origin:
            return True
        expected = app.config["PUBLIC_ORIGIN"] or request.host_url.rstrip("/")
        return origin.rstrip("/") == expected

    def current_player():
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = int(time.time())
        database = get_db()
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        database.commit()
        return database.execute(
            """SELECT p.* FROM players p JOIN sessions s ON s.player_id = p.id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash, now),
        ).fetchone()

    def require_player():
        player = current_player()
        if player is None:
            return None, json_error("Требуется войти в аккаунт", 401)
        return player, None

    def attach_session(response, player_id):
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + SESSION_LIFETIME
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        database = get_db()
        database.execute(
            "INSERT INTO sessions (token_hash, player_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, player_id, expires_at),
        )
        database.commit()
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_LIFETIME,
            httponly=True,
            secure=app.config["COOKIE_SECURE"],
            samesite="Lax",
            path="/",
        )
        return response

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        return send_from_directory(BASE_DIR, "games_5_7.html")

    @app.get("/games_5_7.html")
    def game_page():
        return send_from_directory(BASE_DIR, "games_5_7.html")

    @app.post("/api/auth/register")
    def register():
        if not origin_is_allowed():
            return json_error("Источник запроса не разрешен", 403)
        payload = request_json()
        if payload is None:
            return json_error("Ожидался JSON-запрос", 400)

        email = str(payload.get("email", "")).strip().lower()
        username = str(payload.get("username", "")).strip()
        password = payload.get("password")
        if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
            return json_error("Укажите корректную почту", 400)
        if not USERNAME_PATTERN.fullmatch(username):
            return json_error("Имя: 3–24 символа, буквы, цифры и _", 400)
        if not isinstance(password, str) or not 10 <= len(password) <= 256:
            return json_error("Пароль должен содержать от 10 до 256 символов", 400)

        database = get_db()
        try:
            cursor = database.execute(
                """INSERT INTO players (email, username, password_hash, created_at)
                   VALUES (?, ?, ?, ?)""",
                (email, username, generate_password_hash(password, method="scrypt"), int(time.time())),
            )
            database.commit()
        except sqlite3.IntegrityError:
            database.rollback()
            return json_error("Почта или игровое имя уже заняты", 409)

        player = database.execute("SELECT * FROM players WHERE id = ?", (cursor.lastrowid,)).fetchone()
        response = jsonify({"user": player_json(player)})
        response.status_code = 201
        return attach_session(response, player["id"])

    @app.post("/api/auth/login")
    def login():
        if not origin_is_allowed():
            return json_error("Источник запроса не разрешен", 403)
        payload = request_json()
        if payload is None:
            return json_error("Ожидался JSON-запрос", 400)
        email = str(payload.get("email", "")).strip().lower()
        password = payload.get("password")
        player = get_db().execute("SELECT * FROM players WHERE email = ?", (email,)).fetchone()
        if not player or not isinstance(password, str) or not check_password_hash(player["password_hash"], password):
            return json_error("Неверная почта или пароль", 401)
        response = jsonify({"user": player_json(player)})
        return attach_session(response, player["id"])

    @app.post("/api/auth/logout")
    def logout():
        if not origin_is_allowed():
            return json_error("Источник запроса не разрешен", 403)
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            database = get_db()
            database.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            database.commit()
        response = jsonify({"ok": True})
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            secure=app.config["COOKIE_SECURE"],
            httponly=True,
            samesite="Lax",
        )
        return response

    @app.get("/api/auth/me")
    def me():
        player = current_player()
        return jsonify({"user": player_json(player) if player else None})

    @app.get("/api/state")
    def get_state():
        player, error = require_player()
        if error:
            return error
        return jsonify({"state": game_state_for(player)})

    @app.post("/api/state")
    def save_state():
        if not origin_is_allowed():
            return json_error("Источник запроса не разрешен", 403)
        player, error = require_player()
        if error:
            return error
        payload = request_json()
        state = payload.get("state") if payload else None
        if not isinstance(state, dict):
            return json_error("Некорректное сохранение игры", 400)
        bets = state.get("bets", {})
        allowed_bets = {"slots", "blackjack", "roulette", "crash", "dice", "mines", "coinflip", "highlow", "cups", "poker"}
        if not isinstance(bets, dict) or any(
            key not in allowed_bets or not valid_bet(value)
            for key, value in bets.items()
        ):
            return json_error("Некорректные пользовательские настройки", 400)
        preferences = json.dumps(
            {"sound": state.get("sound") is not False, "bets": bets},
            separators=(",", ":"),
        )
        database = get_db()
        database.execute("UPDATE players SET game_state = ? WHERE id = ?", (preferences, player["id"]))
        database.commit()
        return jsonify({"ok": True})

    @app.get("/api/games/active")
    def active_game():
        player, error = require_player()
        if error:
            return error
        state = json.loads(player["active_round"]) if player["active_round"] else None
        return jsonify({
            "round_id": state["id"] if state else None,
            "game": state["game"] if state else None,
            "round": game_engine.public_round(state) if state else None,
            "user": player_json(player),
            "state": game_state_for(player),
        })

    @app.post("/api/games/start")
    def start_game():
        if not origin_is_allowed():
            return json_error("Источник запроса не разрешен", 403)
        player, error = require_player()
        if error:
            return error
        payload = request_json()
        if payload is None:
            return json_error("Ожидался JSON-запрос", 400)
        game = payload.get("game")
        try:
            bet = parse_money(payload.get("bet"))
        except ValueError:
            return json_error("Invalid bet", 400)
        if not isinstance(game, str) or game not in GAME_IDS or bet < 50 or bet % 50:
            return json_error("Некорректная игра или ставка", 400)
        database = get_db()
        database.execute("BEGIN IMMEDIATE")
        player = database.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
        if player["active_round"]:
            database.rollback()
            return json_error("Сначала заверши текущий раунд", 409)
        if bet > player["wallet_balance"]:
            database.rollback()
            return json_error("Недостаточно средств или ставка превышает предел", 400)
        try:
            round_state, public_round, outcome = game_engine.start_round(
                game,
                bet,
                choice=payload.get("choice"),
                options=payload.get("options") if isinstance(payload.get("options"), dict) else {},
                perks=get_perks(player),
            )
        except (ValueError, TypeError) as error:
            database.rollback()
            return json_error(str(error), 400)
        wallet_after_bet = player["wallet_balance"] - bet
        payout = outcome["payout"] if outcome else 0
        wallet_after = wallet_after_bet + payout
        won = outcome["won"] if outcome else 0
        settle_wallet(database, player, wallet_after, bet, won, None if outcome else round_state, play=True)
        database.commit()
        updated = database.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
        return jsonify({"user": player_json(updated), "state": game_state_for(updated), "round_id": None if outcome else round_state["id"], "round": public_round, "outcome": serialize_outcome(outcome)})

    @app.post("/api/games/action")
    def game_action():
        if not origin_is_allowed():
            return json_error("Источник запроса не разрешен", 403)
        player, error = require_player()
        if error:
            return error
        payload = request_json()
        if payload is None:
            return json_error("Ожидался JSON-запрос", 400)
        database = get_db()
        database.execute("BEGIN IMMEDIATE")
        player = database.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
        try:
            round_state = json.loads(player["active_round"] or "null")
            if not isinstance(round_state, dict) or not secrets.compare_digest(str(payload.get("round_id", "")), round_state["id"]):
                database.rollback()
                return json_error("Раунд не найден или уже завершён", 409)
            new_round, public_round, outcome = game_engine.advance_round(
                round_state,
                payload.get("action"),
                payload.get("data") if isinstance(payload.get("data"), dict) else {},
                perks=get_perks(player),
            )
        except (KeyError, TypeError, ValueError) as error:
            database.rollback()
            return json_error(str(error) or "Некорректное действие", 400)
        extra_bet = int(public_round.get("extra_bet", 0))
        if extra_bet > player["wallet_balance"]:
            database.rollback()
            return json_error("Недостаточно средств для удвоения", 400)
        wallet_after = player["wallet_balance"] - extra_bet + (outcome["payout"] if outcome else 0)
        won = outcome["won"] if outcome else 0
        settle_wallet(database, player, wallet_after, extra_bet, won, None if outcome else new_round, play=False)
        database.commit()
        updated = database.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
        return jsonify({"user": player_json(updated), "state": game_state_for(updated), "round_id": None if outcome else new_round["id"], "round": public_round, "outcome": serialize_outcome(outcome)})

    @app.post("/api/score/event")
    def reject_client_score():
        player, error = require_player()
        if error:
            return error
        return json_error("Рейтинг начисляется только сервером при завершении раунда", 410)

    @app.get("/api/leaderboard")
    def leaderboard():
        players = get_db().execute(
            """SELECT username, total_won_exact, biggest_win_exact, plays FROM players
               ORDER BY length(total_won_exact) DESC, total_won_exact DESC, length(biggest_win_exact) DESC, biggest_win_exact DESC, created_at ASC LIMIT 100"""
        ).fetchall()
        return jsonify({"players": [{"username": p["username"], "total_won": money_json(p["total_won"]), "biggest_win": money_json(p["biggest_win"]), "plays": p["plays"]} for p in players]})

    return app


app = create_app()


if __name__ == "__main__":
    from waitress import serve

    serve(app, host="127.0.0.1", port=8000)
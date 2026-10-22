import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from flask import send_file
from werkzeug.serving import make_server
from backend.app import create_app


@unittest.skipUnless(os.environ.get("BETON_CHROME") and os.environ.get("BETON_NODE"), "Set BETON_CHROME and BETON_NODE for browser checks")
class CupsBrowserTests(unittest.TestCase):
    def test_preview_tracking_results_resize_and_recovery(self):
        self.run_page("cups_browser.html")

    def test_huge_account_wallet_survives_wins_login_and_reload(self):
        import sqlite3
        from contextlib import closing
        from unittest.mock import patch
        from flask import request, jsonify
        def prepare(app, database_path):
            @app.post("/__seed_test_wallet")
            def seed_wallet():
                amount = request.get_json()["amount"]
                if not isinstance(amount, str) or not amount.isdigit():
                    return jsonify(error="Invalid test amount"), 400
                with closing(sqlite3.connect(database_path)) as database:
                    database.execute("UPDATE players SET wallet_balance_exact = ?", (amount,))
                    database.commit()
                return jsonify(ok=True)
        with patch("backend.game_engine.RNG.randrange", return_value=0):
            self.run_page("balance_browser.html", prepare)

    def test_reward_buttons_credit_and_persist_account_wallet(self):
        import sqlite3
        from contextlib import closing
        from unittest.mock import patch
        from flask import request, jsonify
        def prepare(app, database_path):
            @app.post("/__seed_test_wallet")
            def seed_wallet():
                with closing(sqlite3.connect(database_path)) as database:
                    database.execute("UPDATE players SET wallet_balance_exact = ?", (str(request.get_json()["amount"]),))
                    database.commit()
                return jsonify(ok=True)
        with patch("backend.game_engine.RNG.randrange", return_value=0):
            self.run_page("rewards_browser.html", prepare)

    def test_highlow_account_and_guest_share_ui_and_accept_ties(self):
        from unittest.mock import patch
        from flask import request, jsonify
        scenario = {"rank": 7}
        def prepare(app, _database):
            @app.post("/__highlow_test_rank")
            def set_rank():
                rank = request.get_json()["rank"]
                if type(rank) is not int or not 2 <= rank <= 14:
                    return jsonify(error="Invalid rank"), 400
                scenario["rank"] = rank
                return jsonify(ok=True)
        with patch("backend.game_engine.RNG.randint", side_effect=lambda *_args: scenario["rank"]):
            self.run_page("highlow_browser.html", prepare)

    def test_account_card_games_keep_server_hands_and_stakes(self):
        self.run_account_scenarios("account_cards_browser.html")

    def test_account_games_actions_outcomes_and_cleanup(self):
        self.run_account_scenarios("account_games_browser.html")

    def run_account_scenarios(self, page):
        import sqlite3
        from contextlib import closing, ExitStack
        from unittest.mock import patch
        from flask import request, jsonify
        from backend import game_engine
        scenario = {"name": "blackjack"}
        original_sample = game_engine.RNG.sample
        original_randrange = game_engine.RNG.randrange
        original_randint = game_engine.RNG.randint
        original_random = game_engine.RNG.random
        original_deck = game_engine.new_deck
        def deck():
            name = scenario["name"]
            if name.startswith("blackjack"):
                sequence = [("8", "♥"), ("7", "♠"), ("9", "♦"), ("7", "♣"), ("2", "♥"), ("5", "♣")]
                if name == "blackjack_21":
                    sequence[4] = ("6", "♥")
                if name == "blackjack_natural":
                    sequence = [("A", "♠"), ("K", "♥"), ("9", "♦"), ("7", "♣")]
                return [{"r": rank, "s": suit} for rank, suit in reversed(sequence)]
            if name == "poker":
                return [{"r": rank, "s": suit} for rank, suit in reversed([
                    ("J", "♠"), ("J", "♥"), ("4", "♣"), ("6", "♦"), ("8", "♠"),
                    ("9", "♣"), ("2", "♦"), ("5", "♥")])]
            return original_deck()
        def sample(population, count):
            if scenario["name"].startswith("mines") and len(population) == 25:
                return list(range(count))
            return original_sample(population, count)
        def randrange(*args):
            if scenario["name"] in ("roulette", "coinflip"):
                return 0
            return original_randrange(*args)
        def randint(first, last):
            if scenario["name"] == "dice":
                return 4
            if scenario["name"] == "highlow":
                return 7
            return original_randint(first, last)
        def random():
            if scenario["name"] == "crash":
                return 0.9
            if scenario["name"] == "crash_instant":
                return 0.0
            return original_random()
        def prepare(app, database_path):
            app.add_url_rule("/__account_browser_common.js", endpoint="account_browser_common", view_func=lambda: send_file(Path(__file__).with_name("account_browser_common.js")))
            @app.post("/__account_test_scenario")
            def set_scenario():
                payload = request.get_json()
                with closing(sqlite3.connect(database_path)) as database:
                    if database.execute("SELECT active_round FROM players").fetchone()[0]:
                        return jsonify(error="Previous round was not settled"), 409
                    scenario["name"] = payload["name"]
                    progress = {"storyFlags": {"protectedDistrict": True}} if payload["name"] == "mines_protected" else {}
                    database.execute("UPDATE players SET wallet_balance_exact = ?, progress_state = ?", (str(payload.get("balance", 20000)), json.dumps(progress)))
                    database.commit()
                return jsonify(ok=True)
        with ExitStack() as stack:
            for name, replacement in (("new_deck", deck), ("RNG.sample", sample), ("RNG.randrange", randrange), ("RNG.randint", randint), ("RNG.random", random)):
                stack.enter_context(patch("backend.game_engine." + name, side_effect=replacement))
            stack.enter_context(patch("backend.game_engine.RNG.choices", return_value=["7", "7", "7"]))
            self.run_page(page, prepare)

    def run_page(self, page, prepare=None):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({"TESTING": True, "DATABASE": str(Path(directory) / "test.sqlite3"),
                              "COOKIE_SECURE": False, "PUBLIC_ORIGIN": ""})
            app.add_url_rule("/__cups_check", view_func=lambda: send_file(Path(__file__).with_name(page)))
            if prepare:
                prepare(app, app.config["DATABASE"])
            # The test harness embeds the real page; production keeps X-Frame-Options: DENY.
            def allow_test_frame(response):
                response.headers.pop("X-Frame-Options", None)
                return response
            app.after_request_funcs[None].insert(0, allow_test_frame)
            server = make_server("127.0.0.1", 0, app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run([os.environ["BETON_NODE"], str(Path(__file__).with_name("run_cups_browser.cjs")),
                    os.environ["BETON_CHROME"], str(Path(directory) / "chrome"),
                    f"http://127.0.0.1:{server.server_port}/__cups_check"], capture_output=True, timeout=60,
                    encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                self.assertNotEqual(result.stdout.strip(), "RUNNING", "Browser check did not complete")
                report = json.loads(result.stdout.strip())
                self.assertTrue(report.get("ok"), report)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

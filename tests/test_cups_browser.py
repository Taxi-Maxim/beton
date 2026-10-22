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

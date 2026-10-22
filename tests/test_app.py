import os
import tempfile
import unittest

from backend.app import create_app


class AccountApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": os.path.join(self.temp_dir.name, "test.sqlite3"),
                "COOKIE_SECURE": False,
                "PUBLIC_ORIGIN": "http://localhost",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def register(self, email="player@example.com", username="beton_player"):
        return self.client.post(
            "/api/auth/register",
            json={"email": email, "username": username, "password": "long-password-123"},
            headers={"Origin": "http://localhost"},
        )

    def test_home_serves_frontend_from_project_root(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("БЕТОН", response.get_data(as_text=True))
        response.close()

    def test_registration_creates_account_and_http_only_session(self):
        response = self.register()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["user"]["username"], "beton_player")
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertEqual(self.client.get("/api/auth/me").json["user"]["email"], "player@example.com")

    def test_guest_session_check_returns_empty_profile(self):
        response = self.client.get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json["user"])

    def test_duplicate_account_is_rejected(self):
        self.register()
        response = self.register(email="another@example.com")

        self.assertEqual(response.status_code, 409)

    def test_client_score_events_are_rejected_and_cannot_change_leaderboard(self):
        self.register()
        self.client.post("/api/auth/logout", json={})
        login = self.client.post(
            "/api/auth/login",
            json={"email": "player@example.com", "password": "long-password-123"},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(login.status_code, 200)

        score = self.client.post(
            "/api/score/event",
            json={"plays": 1, "won": 10**12, "biggest_win": 10**12},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(score.status_code, 410)
        leaderboard = self.client.get("/api/leaderboard").json["players"]
        self.assertEqual(leaderboard[0]["total_won"], 0)
        self.assertEqual(leaderboard[0]["plays"], 0)

        self.client.post("/api/auth/logout", json={}, headers={"Origin": "http://localhost"})
        self.assertEqual(self.client.post("/api/score/event", json={"plays": 1}).status_code, 401)

    def test_game_state_cannot_overwrite_wallet_or_progress(self):
        self.register()
        saved = self.client.post(
            "/api/state",
            json={"state": {"balance": 10**12, "owned": ["risk_protocol"], "stats": {"won": 10**12, "plays": 999}, "sound": False, "bets": {"slots": 500}}},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(saved.status_code, 200)

        state = self.client.get("/api/state").json["state"]
        self.assertEqual(state["balance"], 5000)
        self.assertEqual(state["owned"], [])
        self.assertEqual(state["stats"]["won"], 0)
        self.assertEqual(state["stats"]["plays"], 0)
        self.assertFalse(state["sound"])
        self.assertEqual(state["bets"]["slots"], 500)

    def test_server_game_round_ignores_client_payout_and_is_one_time(self):
        self.register()
        started = self.client.post(
            "/api/games/start",
            json={"game": "cups", "bet": 100, "payout": 10**12},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json["state"]["balance"], 4900)
        round_id = started.json["round_id"]

        action = self.client.post(
            "/api/games/action",
            json={"round_id": round_id, "action": "pick", "data": {"cup": 99, "payout": 10**12}},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(action.status_code, 400)

        settled = self.client.post(
            "/api/games/action",
            json={"round_id": round_id, "action": "pick", "data": {"cup": started.json["round"].get("ball", 0), "payout": 10**12}},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(settled.status_code, 200)
        self.assertIn(settled.json["state"]["balance"], (4900, 5170))
        self.assertLessEqual(settled.json["user"]["total_won"], 270)

        replay = self.client.post(
            "/api/games/action",
            json={"round_id": round_id, "action": "pick", "data": {"cup": 0}},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(replay.status_code, 409)

    def test_wallet_and_preferences_survive_login(self):
        self.register()
        state = {"balance": 8125, "sound": False, "bets": {"slots": 500}, "owned": ["watch"]}
        saved = self.client.post(
            "/api/state",
            json={"state": state},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(saved.status_code, 200)
        self.client.post("/api/auth/logout", json={})
        self.assertEqual(self.client.get("/api/state").status_code, 401)

        self.client.post(
            "/api/auth/login",
            json={"email": "player@example.com", "password": "long-password-123"},
            headers={"Origin": "http://localhost"},
        )
        restored = self.client.get("/api/state")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json["state"]["balance"], 5000)
        self.assertEqual(restored.json["state"]["owned"], [])
        self.assertFalse(restored.json["state"]["sound"])
        self.assertEqual(restored.json["state"]["bets"]["slots"], 500)

    def test_sql_injection_cannot_log_in_or_change_wallet(self):
        self.register()
        self.client.post("/api/auth/logout", json={})
        response = self.client.post("/api/auth/login", json={
            "email": "' OR 1=1 --", "password": "wrong-password"})
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(self.client.get("/api/auth/me").json["user"])
        self.client.post("/api/auth/login", json={
            "email": "player@example.com", "password": "long-password-123"})
        for bet in [True, -100, 1.5, "50; DROP TABLE players", "NaN", "1e30"]:
            with self.subTest(bet=bet):
                response = self.client.post("/api/games/start", json={"game": "coinflip", "bet": bet})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/state").json["state"]["balance"], 5000)

    def test_huge_wallet_payout_and_restart_are_exact(self):
        import sqlite3
        from unittest.mock import patch
        from contextlib import closing
        self.register()
        amount = 10**5000
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as database:
            database.execute("UPDATE players SET wallet_balance_exact = ?", (str(amount),))
            database.commit()
        with patch("backend.game_engine.RNG.randrange", return_value=0):
            response = self.client.post("/api/games/start", json={
                "game": "coinflip", "bet": str(amount), "choice": "heads"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["state"]["balance"], str(amount * 2))
        self.assertEqual(response.json["outcome"]["payout"], str(amount * 2))
        self.assertEqual(self.client.get("/api/leaderboard").json["players"][0]["total_won"], str(amount * 2))
        restarted = create_app(dict(self.app.config)).test_client()
        restarted.post("/api/auth/login", json={"email": "player@example.com", "password": "long-password-123"})
        self.assertEqual(restarted.get("/api/state").json["state"]["balance"], str(amount * 2))

    def test_huge_multistep_payout_and_replay_are_exact(self):
        import sqlite3
        from unittest.mock import patch
        from contextlib import closing
        self.register()
        amount = 10**100
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as database:
            database.execute("UPDATE players SET wallet_balance_exact = ?", (str(amount),))
            database.commit()
        with patch("backend.game_engine.RNG.randrange", return_value=1):
            started = self.client.post("/api/games/start", json={"game": "cups", "bet": str(amount)})
        payload = {"round_id": started.json["round_id"], "action": "pick", "data": {"cup": 1}}
        response = self.client.post("/api/games/action", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["state"]["balance"], str(amount * 27 // 10))
        self.assertEqual(self.client.post("/api/games/action", json=payload).status_code, 409)

    def test_concurrent_settlement_credits_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        self.register()
        with patch("backend.game_engine.RNG.randrange", return_value=1):
            started = self.client.post("/api/games/start", json={"game": "cups", "bet": 100})
        cookie = self.client.get_cookie("beton_session").value
        payload = {"round_id": started.json["round_id"], "action": "pick", "data": {"cup": 1}}
        def settle(_):
            client = self.app.test_client()
            client.set_cookie("beton_session", cookie)
            return client.post("/api/games/action", json=payload).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(settle, range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(self.client.get("/api/state").json["state"]["balance"], 5170)

    def test_trillion_balance_survives_winnings_and_login(self):
        import sqlite3
        from contextlib import closing
        from unittest.mock import patch
        self.register()
        for amount in (999_999_999_950, 1_000_000_000_050, 9_007_199_254_741_000):
            with self.subTest(amount=amount):
                with closing(sqlite3.connect(self.app.config["DATABASE"])) as database:
                    database.execute("UPDATE players SET wallet_balance_exact = ?", (str(amount),))
                    database.commit()
                with patch("backend.game_engine.RNG.randrange", return_value=0):
                    result = self.client.post("/api/games/start", json={"game": "coinflip", "bet": str(amount), "choice": "heads"})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(int(result.json["state"]["balance"]), amount * 2)
                self.client.post("/api/auth/logout", json={})
                self.client.post("/api/auth/login", json={"email": "player@example.com", "password": "long-password-123"})
                self.assertEqual(int(self.client.get("/api/state").json["state"]["balance"]), amount * 2)

    def test_legacy_scientific_wallet_is_migrated_without_reset(self):
        import sqlite3
        from contextlib import closing
        self.register()
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as database:
            database.execute("UPDATE players SET wallet_balance_exact = '1e+100', total_won_exact = '1.2345e+30'")
            database.commit()
        restored = create_app(dict(self.app.config)).test_client()
        restored.post("/api/auth/login", json={"email": "player@example.com", "password": "long-password-123"})
        state = restored.get("/api/state").json["state"]
        self.assertEqual(state["balance"], str(10**100))
        self.assertEqual(state["stats"]["won"], str(12345 * 10**26))

    def test_cross_site_without_origin_is_rejected(self):
        self.register()
        response = self.client.post("/api/games/start", json={"game": "cups", "bet": 100},
                                    headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403)

    def test_cross_origin_registration_is_rejected(self):
        response = self.client.post(
            "/api/auth/register",
            json={"email": "player@example.com", "username": "beton_player", "password": "long-password-123"},
            headers={"Origin": "https://attacker.invalid"},
        )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
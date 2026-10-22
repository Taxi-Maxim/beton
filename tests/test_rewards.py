import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from backend.app import create_app


class RewardApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE": os.path.join(self.directory.name, "test.sqlite3"), "COOKIE_SECURE": False, "PUBLIC_ORIGIN": "http://localhost"})
        self.client = self.app.test_client()
        self.client.post("/api/auth/register", json={"email": "rewards@example.com", "username": "rewards_test", "password": "test-password-123"})

    def tearDown(self):
        self.directory.cleanup()

    def seed(self, balance=5000, plays=0, progress=None):
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as database:
            database.execute("UPDATE players SET wallet_balance_exact = ?, plays = ?, progress_state = ?", (str(balance), plays, json.dumps(progress or {})))
            database.commit()

    def challenge(self):
        response = self.client.post("/api/refill/challenge", json={})
        self.assertEqual(response.status_code, 200)
        return {"challenge_id": response.json["challenge_id"], "answer": response.json["a"] * response.json["b"]}

    def state(self):
        return self.client.get("/api/state").json["state"]

    def test_quest_credits_once_and_persists(self):
        self.seed(balance=10**100, plays=5)
        response = self.client.post("/api/quests/claim", json={"quest_id": "first5", "reward": 10**100})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(int(response.json["state"]["balance"]), 10**100 + 3000)
        self.assertEqual(response.json["state"]["stats"]["won"], 0)
        self.assertEqual(response.json["state"]["reputation"], 10)
        self.assertEqual(self.client.post("/api/quests/claim", json={"quest_id": "first5"}).status_code, 409)
        self.client.post("/api/auth/logout", json={})
        self.client.post("/api/auth/login", json={"email": "rewards@example.com", "password": "test-password-123"})
        self.assertEqual(self.state()["claimed"], ["first5"])
        self.assertEqual(int(self.state()["balance"]), 10**100 + 3000)

    def test_quest_requires_server_progress(self):
        self.client.post("/api/state", json={"state": {"stats": {"plays": 9999}, "claimed": [], "balance": 10**100}})
        self.assertEqual(self.client.post("/api/quests/claim", json={"quest_id": "first5"}).status_code, 409)
        self.assertEqual(self.client.post("/api/quests/claim", json={"quest_id": "unknown"}).status_code, 400)
        self.assertEqual(self.state()["balance"], 5000)
        self.assertEqual(self.state()["claimed"], [])

    def test_quest_bonuses_match_display_rounding(self):
        self.seed(plays=5, progress={"owned": ["profit_share"], "storyFlags": {"investedHall": True}})
        response = self.client.post("/api/quests/claim", json={"quest_id": "first5"})
        self.assertEqual(response.json["reward"], 3308)
        self.assertEqual(response.json["state"]["balance"], 8308)

    def test_refill_answer_credits_5000_and_enforces_cooldown(self):
        self.seed(balance=499)
        payload = self.challenge()
        response = self.client.post("/api/refill/claim", json={**payload, "reward": 10**100})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["state"]["balance"], 5499)
        self.assertGreater(response.json["state"]["lastRefill"], 0)
        self.assertEqual(self.client.post("/api/refill/claim", json=payload).status_code, 409)
        self.seed(balance=0, progress={"lastRefill": response.json["state"]["lastRefill"]})
        self.assertEqual(self.client.post("/api/refill/challenge", json={}).status_code, 429)

    def test_wrong_and_expired_answers_never_credit(self):
        self.seed(balance=0)
        payload = self.challenge()
        self.assertEqual(self.client.post("/api/refill/claim", json={"challenge_id": "wrong", "answer": 1}).status_code, 409)
        self.assertEqual(self.client.post("/api/refill/claim", json={**payload, "answer": -1}).status_code, 400)
        self.assertEqual(self.client.post("/api/refill/claim", json=payload).status_code, 409)
        payload = self.challenge()
        with closing(sqlite3.connect(self.app.config["DATABASE"])) as database:
            database.execute("UPDATE refill_challenges SET expires_at = 0")
            database.commit()
        self.assertEqual(self.client.post("/api/refill/claim", json=payload).status_code, 400)
        self.assertEqual(self.state()["balance"], 0)

    def test_refill_rechecks_wallet_and_blocks_active_rounds(self):
        self.assertEqual(self.client.post("/api/refill/challenge", json={}).status_code, 409)
        self.seed(balance=500)
        payload = self.challenge()
        self.seed(balance=501)
        self.assertEqual(self.client.post("/api/refill/claim", json=payload).status_code, 409)
        self.seed(balance=500)
        self.client.post("/api/games/start", json={"game": "cups", "bet": 500})
        self.assertEqual(self.client.post("/api/refill/challenge", json={}).status_code, 409)

    def test_concurrent_claims_credit_once(self):
        cookie = self.client.get_cookie("beton_session").value
        def race(path, payload):
            def claim(_):
                client = self.app.test_client()
                client.set_cookie("beton_session", cookie)
                return client.post(path, json=payload).status_code
            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertEqual(sorted(executor.map(claim, range(2))), [200, 409])
        self.seed(plays=5)
        race("/api/quests/claim", {"quest_id": "first5"})
        self.assertEqual(self.state()["balance"], 8000)
        self.seed(balance=0)
        race("/api/refill/claim", self.challenge())
        self.assertEqual(self.state()["balance"], 5000)

    def test_shop_records_real_purchases_and_unlocks_collector(self):
        for item in ("pen", "boots", "jacket"):
            response = self.client.post("/api/shop/buy", json={"item_id": item, "price": 0})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state()["balance"], 4230)
        self.assertEqual(self.state()["stats"]["purchases"], 3)
        self.assertEqual(self.client.post("/api/shop/buy", json={"item_id": "pen"}).status_code, 409)
        response = self.client.post("/api/quests/claim", json={"quest_id": "collector"})
        self.assertEqual(response.json["state"]["balance"], 14230)
        self.assertEqual(self.client.post("/api/shop/buy", json={"item_id": "moon"}).status_code, 409)
        self.assertEqual(self.state()["balance"], 14230)
        self.assertEqual(self.state()["stats"]["purchases"], 3)

    def test_shop_catalog_matches_visible_prices(self):
        import re
        from pathlib import Path
        from backend.catalog import SHOP_ITEMS
        page = (Path(__file__).resolve().parent.parent / "games_5_7.html").read_text(encoding="utf-8")
        items = page.split("const ITEMS=[", 1)[1].split("const TIERS=", 1)[0]
        visible = {item: (int(price), int(tier)) for item, price, tier in
                   re.findall(r"\{id:'([^']+)'.*?price:(\d+).*?tier:(\d+)", items)}
        self.assertEqual(SHOP_ITEMS, visible)

    def test_reward_routes_require_account_and_same_origin(self):
        for route in ("/api/shop/buy", "/api/quests/claim", "/api/refill/challenge", "/api/refill/claim"):
            self.assertEqual(self.client.post(route, json={}, headers={"Origin": "https://other.invalid"}).status_code, 403)
        self.client.post("/api/auth/logout", json={})
        for route in ("/api/shop/buy", "/api/quests/claim", "/api/refill/challenge", "/api/refill/claim"):
            self.assertEqual(self.client.post(route, json={}).status_code, 401)

import unittest
from unittest.mock import patch

from backend.game_engine import advance_round, start_round, poker_payout, public_round


class ServerGameEngineTests(unittest.TestCase):
    def test_every_game_generates_outcomes_or_server_round_state(self):
        choices = {
            "roulette": "red",
            "dice": "more",
            "coinflip": "heads",
            "mines": None,
        }
        for game in ("slots", "blackjack", "roulette", "dice", "coinflip", "cups", "highlow", "mines", "crash", "poker"):
            with self.subTest(game=game):
                state, public, result = start_round(game, 100, choice=choices.get(game), options={"mines": 5})
                self.assertEqual(state["game"], game)
                self.assertTrue(public)
                self.assertTrue(result is None or 0 <= result["payout"] <= 10_000)

    def test_cups_payout_uses_server_stored_ball(self):
        state, _public, result = start_round("cups", 100)

        self.assertIsNone(result)
        winning_state, public, result = advance_round(
            state,
            "pick",
            {"cup": state["ball"], "payout": 10**12},
            {},
        )

        self.assertEqual(public["ball"], state["ball"])
        self.assertEqual(result["payout"], 270)
        self.assertEqual(result["won"], 270)
        self.assertFalse(winning_state["phase"] == "pick")

    def test_cup_preview_and_swaps_match_the_paid_position(self):
        for _ in range(100):
            state, public, _ = start_round("cups", 100)
            order = [0, 1, 2]
            self.assertEqual(len(public["swaps"]), 28)
            for slots in public["swaps"]:
                self.assertIn(len(slots), (2, 3))
                self.assertEqual(len(slots), len(set(slots)))
                moved = [order[slot] for slot in slots]
                for slot, cup in zip(slots, moved[-1:] + moved[:-1]):
                    order[slot] = cup
            picked = order.index(public["preview_ball"])
            self.assertEqual(picked, state["ball"])
            self.assertEqual(public_round(state), public)
            _, revealed, outcome = advance_round(state, "pick", {"cup": picked})
            self.assertEqual(revealed["ball"], picked)
            self.assertEqual(outcome["payout"], 270)

    def test_legacy_cup_round_replays_without_changing_winner(self):
        state = {"game": "cups", "bet": 100, "ball": 1, "phase": "pick"}
        public = public_round(state)
        order = [0, 1, 2]
        for first, second in public["swaps"]:
            order[first], order[second] = order[second], order[first]
        self.assertEqual(order.index(public["preview_ball"]), 1)
        self.assertNotIn("swaps", state)
        self.assertEqual(public_round(state), public)

    def test_highlow_ties_win_for_both_directions_and_extreme_cards(self):
        for current in (2, 7, 14):
            for action in ("higher", "lower"):
                with self.subTest(current=current, action=action):
                    state = {"game": "highlow", "bet": 100, "current": current, "multiplier": 1.0, "rounds": 0, "phase": "guess"}
                    with patch("backend.game_engine.RNG.randint", return_value=current):
                        updated, public, outcome = advance_round(state, action, {"payout": 10**12})
                    self.assertIsNone(outcome)
                    self.assertTrue(public["tie"])
                    self.assertEqual(updated["rounds"], 1)
                    winning = 15 - current if action == "higher" else current - 1
                    self.assertAlmostEqual(updated["multiplier"], 0.96 * 13 / winning)
                    _, _, result = advance_round(updated, "cashout")
                    self.assertEqual(result["result"], "win")
                    self.assertLess(result["payout"], 1300)

    def test_highlow_wrong_direction_still_loses(self):
        for action, next_card in (("higher", 6), ("lower", 8)):
            state = {"game": "highlow", "bet": 100, "current": 7, "multiplier": 1.0, "rounds": 0, "phase": "guess"}
            with patch("backend.game_engine.RNG.randint", return_value=next_card):
                _, _, result = advance_round(state, action)
            self.assertEqual(result["payout"], 0)

    def test_mines_result_comes_from_server_layout(self):
        state = {"game": "mines", "bet": 100, "mines": [3], "opened": [], "mine_count": 1, "phase": "active"}
        _updated, public, result = advance_round(state, "open", {"tile": 3, "won": 10**12})

        self.assertEqual(public["mine"], 3)
        self.assertEqual(result["payout"], 0)

    def test_mines_cashout_and_expired_crash(self):
        state = {"game": "mines", "bet": 10**100, "mines": [3], "opened": [1], "mine_count": 1, "phase": "active"}
        _updated, _public, result = advance_round(state, "cashout")
        self.assertGreater(result["payout"], 10**100)
        state = {"game": "crash", "bet": 100, "started_at": 0, "growth_rate": 0.2, "crash_point": 2, "phase": "active"}
        _updated, public, result = advance_round(state, "cashout")
        self.assertTrue(public["crashed"])
        self.assertEqual(result["payout"], 0)

    def test_poker_face_cards_are_distinct_ranks(self):
        hand = [{"r": rank, "s": suit} for rank, suit in
                zip(["10", "J", "Q", "K", "2"], ["s", "h", "d", "c", "s"])]
        self.assertEqual(poker_payout(hand)[1], 0)
        royal = [{"r": rank, "s": "s"} for rank in ["10", "J", "Q", "K", "A"]]
        self.assertEqual(poker_payout(royal)[1], 100)
        wheel = [{"r": rank, "s": suit} for rank, suit in
                 zip(["A", "2", "3", "4", "5"], ["s", "h", "d", "c", "s"])]
        self.assertEqual(poker_payout(wheel)[1], 5)

    def test_blackjack_hit_to_21_finishes_without_replacing_cards(self):
        player = [{"r": "8", "s": "h"}, {"r": "7", "s": "s"}]
        dealer = [{"r": "9", "s": "d"}, {"r": "7", "s": "c"}]
        state = {"game": "blackjack", "bet": 100, "player": player.copy(), "dealer": dealer.copy(),
                 "deck": [{"r": "5", "s": "c"}, {"r": "6", "s": "h"}], "phase": "play"}
        self.assertIsNone(public_round(state)["dealer"][1])
        updated, public, outcome = advance_round(state, "hit")
        self.assertEqual(updated["phase"], "over")
        self.assertEqual(outcome["result"], "push")
        self.assertEqual(public["player"][:2], player)
        self.assertEqual(public["dealer"][:2], dealer)
        self.assertNotIn(None, public["dealer"])

    def test_finished_natural_blackjack_has_finished_state(self):
        deck = [{"r": "7", "s": "c"}, {"r": "9", "s": "d"}, {"r": "K", "s": "h"}, {"r": "A", "s": "s"}]
        with patch("backend.game_engine.new_deck", return_value=deck):
            state, public, outcome = start_round("blackjack", 100)
        self.assertEqual(state["phase"], "over")
        self.assertEqual(public_round(state), public)
        self.assertEqual(outcome["payout"], 250)

    def test_invalid_instant_game_selections_are_rejected(self):
        for game in ("roulette", "dice", "coinflip"):
            for choice in (None, "unknown", [], {}):
                with self.subTest(game=game, choice=choice), self.assertRaises(ValueError):
                    start_round(game, 100, choice=choice)

    def test_mines_recovery_preserves_protected_multiplier(self):
        state = {"game": "mines", "bet": 100, "opened": [2], "mines": [0], "mine_count": 1, "phase": "active"}
        public = public_round(state, {"protectedDistrict": True})
        self.assertAlmostEqual(public["multiplier"], 25 / 24 * 1.02)

    def test_rejects_invalid_actions_and_selections(self):
        cups = {"game": "cups", "bet": 100, "ball": 1, "phase": "pick"}
        with self.assertRaises(ValueError):
            advance_round(cups, "pick", {"cup": 99})
        with self.assertRaises(ValueError):
            start_round("mines", 100, options={"mines": 25})


if __name__ == "__main__":
    unittest.main()

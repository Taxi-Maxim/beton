from fractions import Fraction
import math
import secrets
import time


RNG = secrets.SystemRandom()
SUITS = ["\u2660", "\u2665", "\u2666", "\u2663"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SLOT_SYMBOLS = ["7", "\U0001f48e", "\U0001f480", "\U0001f514", "\U0001f525", "\U0001f340", "BAR", "\U0001f352"]
SLOT_WEIGHTS = [2, 3, 4, 5, 6, 7, 6, 8]
SLOT_PAYOUTS = {"7": 50, "\U0001f48e": 30, "\U0001f480": 25, "\U0001f514": 20, "\U0001f525": 15, "\U0001f340": 12, "BAR": 10, "\U0001f352": 8}
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def card_value(card):
    rank = card["r"]
    if rank == "A":
        return 11
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def hand_value(hand):
    total = sum(card_value(card) for card in hand)
    aces = sum(card["r"] == "A" for card in hand)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(hand):
    return len(hand) == 2 and hand_value(hand) == 21


def new_deck():
    deck = [{"s": suit, "r": rank} for suit in SUITS for rank in RANKS]
    RNG.shuffle(deck)
    return deck


def money_product(bet, multiplier):
    return round(bet * Fraction(str(multiplier)))


def finish_round(payout=0, won=0, result="lose"):
    return {"active": False, "payout": int(round(payout)), "won": int(round(won)), "result": result}


def public_round(round_state):
    game = round_state["game"]
    phase = round_state.get("phase", "over")
    if game == "blackjack":
        dealer = round_state["dealer"] if phase == "over" else [round_state["dealer"][0], None]
        return {"player": round_state["player"], "dealer": dealer, "phase": phase}
    if game == "mines":
        opened = round_state["opened"]
        multiplier = mines_multiplier(round_state["mine_count"], len(opened)) if opened else 1
        return {"mine_count": round_state["mine_count"], "opened": opened, "phase": phase, "multiplier": multiplier}
    if game == "highlow":
        return {key: round_state[key] for key in ("current", "multiplier", "rounds", "phase")}
    if game == "cups":
        # Older in-progress rounds also get a replayable presentation, without
        # changing their stored winning position or charging another bet.
        swaps = round_state.get("swaps", [[0, 1], [1, 2], [0, 2]] * 3)
        order = [0, 1, 2]
        for slots in swaps:
            before = order.copy()
            for index, slot in enumerate(slots):
                order[slots[(index + 1) % len(slots)]] = before[slot]
        return {"phase": phase, "preview_ball": round_state.get("preview_ball", order[round_state["ball"]]), "swaps": swaps}
    if game == "poker":
        return {"hand": round_state["hand"], "phase": phase}
    if game == "crash":
        elapsed = max(0, time.time() - round_state["started_at"])
        multiplier = min(round_state["crash_point"], math.exp(min(10, elapsed * round_state["growth_rate"])))
        return {"started": True, "multiplier": multiplier, "phase": phase}
    return {"phase": phase}


def mines_multiplier(mine_count, opened, protected=False):
    multiplier = 1.0
    for index in range(opened):
        multiplier *= (25 - index) / (25 - mine_count - index)
    return multiplier * (1.02 if protected else 1)


def poker_payout(hand, atlas=False):
    values = sorted(RANKS.index(card["r"]) + 1 if card["r"] != "A" else 14 for card in hand)
    suits = [card["s"] for card in hand]
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    groups = sorted(counts.values(), reverse=True)
    flush = len(set(suits)) == 1
    unique = sorted(set(values))
    straight = len(unique) == 5 and unique[-1] - unique[0] == 4
    if unique == [2, 3, 4, 5, 14]:
        straight = True
    if flush and unique == [10, 11, 12, 13, 14]:
        return "\u0420\u041e\u042f\u041b-\u0424\u041b\u0415\u0428", 100
    if flush and straight:
        return "\u0421\u0422\u0420\u0418\u0422-\u0424\u041b\u0415\u0428", 50
    if groups[0] == 4:
        return "\u041a\u0410\u0420\u0415", 25
    if groups[0] == 3 and groups[1] == 2:
        return "\u0424\u0423\u041b\u041b-\u0425\u0410\u0423\u0421", 10
    if flush:
        return "\u0424\u041b\u0415\u0428", 7
    if straight:
        return "\u0421\u0422\u0420\u0418\u0422", 5
    if groups[0] == 3:
        return "\u0422\u0420\u041e\u0419\u041a\u0410", 4
    if groups[0] == 2 and groups[1] == 2:
        return "\u0414\u0412\u0415 \u041f\u0410\u0420\u042b", 3
    if groups[0] == 2:
        pair = next(value for value, count in counts.items() if count == 2)
        if pair >= 11:
            return "\u041f\u0410\u0420\u0410", 2.2 if atlas else 2
    return "\u0411\u0415\u0417 \u041a\u041e\u041c\u0411\u0418\u041d\u0410\u0426\u0418\u0418", 0


def start_round(game, bet, choice=None, options=None, perks=None):
    options = options or {}
    perks = perks or {}
    round_state = {"id": secrets.token_urlsafe(18), "game": game, "bet": bet}

    if game == "slots":
        symbols = RNG.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
        multiplier = 0
        if symbols[0] == symbols[1] == symbols[2]:
            multiplier = SLOT_PAYOUTS[symbols[0]]
        elif len(set(symbols)) < 3:
            multiplier = 2.2 if perks.get("slot_token") else 2.05 if perks.get("bold") else 2
        payout = money_product(bet, multiplier)
        return round_state, {"symbols": symbols, "multiplier": multiplier}, finish_round(payout, payout if multiplier else 0, "win" if multiplier else "lose")

    if game == "blackjack":
        deck = new_deck()
        player, dealer = [deck.pop(), deck.pop()], [deck.pop(), deck.pop()]
        round_state.update({"deck": deck, "player": player, "dealer": dealer, "phase": "play"})
        if is_blackjack(player) and is_blackjack(dealer):
            return round_state, {"player": player, "dealer": dealer, "phase": "over"}, finish_round(bet, 0, "push")
        if is_blackjack(player):
            payout = money_product(bet, 2.65 if perks.get("bj_course") else 2.5)
            return round_state, {"player": player, "dealer": dealer, "phase": "over"}, finish_round(payout, payout, "blackjack")
        if is_blackjack(dealer):
            return round_state, {"player": player, "dealer": dealer, "phase": "over"}, finish_round()
        return round_state, {"player": player, "dealer": [dealer[0], None], "phase": "play"}, None

    if game == "roulette":
        number = RNG.randrange(37)
        red = number in RED_NUMBERS
        wins = {"red": red, "black": number != 0 and not red, "green": number == 0,
                "even": number != 0 and number % 2 == 0, "odd": number % 2 == 1,
                "low": 1 <= number <= 18, "high": 19 <= number <= 36}
        is_win = bool(wins.get(choice, False))
        multiplier = (14 + (1 if perks.get("wheel_contact") else 0) + (0.25 if perks.get("hiredMax") else 0)) if choice == "green" else (1.9 if perks.get("capitalDeal") else 2)
        payout = money_product(bet, multiplier) if is_win else 0
        color = "green" if number == 0 else "red" if red else "black"
        return round_state, {"number": number, "color": color}, finish_round(payout, payout, "win" if is_win else "lose")

    if game == "dice":
        dice = [RNG.randint(1, 6), RNG.randint(1, 6)]
        total = sum(dice)
        multipliers = {"more": 2 if total > 7 else 0, "less": 2 if total < 7 else 0,
                       "seven": (5.5 if perks.get("publicChallenge") else 5) if total == 7 else 0,
                       "pair": (2.75 if perks.get("calibrated_dice") else 2.5) if dice[0] == dice[1] else 0}
        multiplier = multipliers.get(choice, 0)
        payout = money_product(bet, multiplier)
        return round_state, {"dice": dice, "total": total, "multiplier": multiplier}, finish_round(payout, payout, "win" if multiplier else "lose")

    if game == "coinflip":
        result = "heads" if RNG.randrange(2) == 0 else "tails"
        is_win = result == choice
        payout = bet * 2 if is_win else 0
        return round_state, {"result": result}, finish_round(payout, payout, "win" if is_win else "lose")

    if game == "cups":
        swaps = [RNG.sample(range(3), 3 if step >= 4 and RNG.random() < 0.55 else 2) for step in range(28)]
        order = [0, 1, 2]
        for slots in swaps:
            before = order.copy()
            for index, slot in enumerate(slots):
                order[slots[(index + 1) % len(slots)]] = before[slot]
        ball = RNG.randrange(3)
        round_state.update({"ball": ball, "preview_ball": order[ball], "swaps": swaps, "phase": "pick"})
        return round_state, public_round(round_state), None

    if game == "highlow":
        round_state.update({"current": RNG.randint(2, 14), "multiplier": 1.0, "rounds": 0, "phase": "guess"})
        return round_state, {"current": round_state["current"], "multiplier": 1.0, "rounds": 0, "phase": "guess"}, None

    if game == "mines":
        mine_count = options.get("mines", 5)
        if type(mine_count) is not int or not 1 <= mine_count <= 24:
            raise ValueError("\u0427\u0438\u0441\u043b\u043e \u043c\u0438\u043d \u0434\u043e\u043b\u0436\u043d\u043e \u0431\u044b\u0442\u044c \u043e\u0442 1 \u0434\u043e 24")
        mines = sorted(RNG.sample(range(25), mine_count))
        round_state.update({"mines": mines, "opened": [], "mine_count": mine_count, "phase": "active"})
        return round_state, {"mine_count": mine_count, "opened": [], "phase": "active"}, None

    if game == "crash":
        instant_chance = 0.03 if perks.get("trustedGrom") else 0.035
        house_factor = 0.95 if perks.get("risk_protocol") else 0.94
        crash_point = 1 if RNG.random() < instant_chance else min(30, max(1.01, math.floor((house_factor / (1 - RNG.random())) * 100) / 100))
        round_state.update({"crash_point": crash_point, "growth_rate": RNG.uniform(0.16, 0.23), "started_at": time.time(), "phase": "active"})
        return round_state, {"started": True, "phase": "active"}, None

    if game == "poker":
        deck = new_deck()
        hand = [deck.pop() for _ in range(5)]
        round_state.update({"deck": deck, "hand": hand, "phase": "draw"})
        return round_state, {"hand": hand, "phase": "draw"}, None

    raise ValueError("Unknown game")


def advance_round(round_state, action, data=None, perks=None):
    data = data or {}
    perks = perks or {}
    game = round_state["game"]
    bet = round_state["bet"]

    if game == "cups" and round_state.get("phase") == "pick" and action == "pick":
        picked = data.get("cup")
        if type(picked) is not int or not 0 <= picked <= 2:
            raise ValueError("Invalid cup")
        is_win = picked == round_state["ball"]
        multiplier = 2.7 + (0.15 if perks.get("cup_magnet") else 0) + (0.05 if perks.get("choseConnections") else 0)
        payout = money_product(bet, multiplier) if is_win else 0
        round_state["phase"] = "over"
        return round_state, {"cup": picked, "ball": round_state["ball"], "multiplier": multiplier, "phase": "over"}, finish_round(payout, payout, "win" if is_win else "lose")

    if game == "highlow" and round_state.get("phase") == "guess":
        if action == "cashout" and round_state["rounds"] > 0:
            payout = money_product(bet, round_state["multiplier"])
            return round_state, {"current": round_state["current"], "multiplier": round_state["multiplier"], "phase": "over"}, finish_round(payout, payout, "win")
        if action not in ("higher", "lower"):
            raise ValueError("Invalid guess")
        previous = round_state["current"]
        next_card = RNG.randint(2, 14)
        round_state["current"] = next_card
        if next_card == previous or (action == "higher" and next_card < previous) or (action == "lower" and next_card > previous):
            round_state["phase"] = "over"
            return round_state, {"current": next_card, "phase": "over"}, finish_round()
        winning_ranks = 14 - previous if action == "higher" else previous - 2
        rtp = 0.98 if perks.get("counting_ledger") else 0.96
        round_state["multiplier"] = min(20, round_state["multiplier"] * (rtp / (winning_ranks / 13)))
        round_state["rounds"] += 1
        public = {"current": next_card, "phase": "guess", "rounds": round_state["rounds"], "multiplier": round_state["multiplier"]}
        if round_state["multiplier"] >= 20:
            round_state["phase"] = "over"
            public["phase"] = "over"
            payout = money_product(bet, round_state["multiplier"])
            return round_state, public, finish_round(payout, payout, "win")
        return round_state, public, None

    if game == "mines" and round_state.get("phase") == "active":
        opened = round_state["opened"]
        if action == "cashout" and opened:
            payout = money_product(bet, mines_multiplier(round_state["mine_count"], len(opened), perks.get("protectedDistrict", False)))
            round_state["phase"] = "over"
            return round_state, {"opened": opened, "mines": round_state["mines"], "phase": "over"}, finish_round(payout, payout, "win")
        if action != "open":
            raise ValueError("Invalid mines action")
        tile = data.get("tile")
        if type(tile) is not int or not 0 <= tile < 25 or tile in opened:
            raise ValueError("Invalid tile")
        if tile in round_state["mines"]:
            round_state["phase"] = "over"
            return round_state, {"opened": opened, "mine": tile, "mines": round_state["mines"], "phase": "over"}, finish_round()
        opened.append(tile)
        public = {"opened": opened, "phase": "active", "multiplier": mines_multiplier(round_state["mine_count"], len(opened), perks.get("protectedDistrict", False))}
        if len(opened) == 25 - round_state["mine_count"]:
            public["phase"] = "over"
            round_state["phase"] = "over"
            payout = money_product(bet, public["multiplier"])
            return round_state, public, finish_round(payout, payout, "win")
        return round_state, public, None

    if game == "blackjack" and round_state.get("phase") == "play":
        player, dealer, deck = round_state["player"], round_state["dealer"], round_state["deck"]
        extra_bet = 0
        if action == "hit":
            player.append(deck.pop())
            if hand_value(player) > 21:
                round_state["phase"] = "over"
                return round_state, {"player": player, "dealer": dealer, "phase": "over"}, finish_round()
            return round_state, {"player": player, "dealer": [dealer[0], None], "phase": "play"}, None
        if action == "double":
            if len(player) != 2:
                raise ValueError("Double is allowed only after initial deal")
            round_state["bet"] = bet * 2
            extra_bet = bet
            player.append(deck.pop())
            if hand_value(player) > 21:
                round_state["phase"] = "over"
                return round_state, {"player": player, "dealer": dealer, "phase": "over", "extra_bet": extra_bet}, finish_round()
        elif action != "stand":
            raise ValueError("Invalid blackjack action")
        while hand_value(dealer) < 17:
            dealer.append(deck.pop())
        player_total, dealer_total = hand_value(player), hand_value(dealer)
        round_state["phase"] = "over"
        public = {"player": player, "dealer": dealer, "phase": "over", "extra_bet": extra_bet}
        if dealer_total > 21 or player_total > dealer_total:
            payout = round_state["bet"] * 2
            return round_state, public, finish_round(payout, payout, "win")
        if player_total == dealer_total:
            return round_state, public, finish_round(round_state["bet"], 0, "push")
        return round_state, public, finish_round()

    if game == "poker" and round_state.get("phase") == "draw" and action == "draw":
        keep = data.get("keep", [])
        if not isinstance(keep, list) or any(type(index) is not int or not 0 <= index < 5 for index in keep):
            raise ValueError("Invalid cards to keep")
        keep = set(keep)
        hand = round_state["hand"]
        round_state["hand"] = [card if index in keep else round_state["deck"].pop() for index, card in enumerate(hand)]
        name, multiplier = poker_payout(round_state["hand"], perks.get("poker_atlas", False))
        round_state["phase"] = "over"
        payout = money_product(bet, multiplier)
        return round_state, {"hand": round_state["hand"], "name": name, "multiplier": multiplier, "phase": "over"}, finish_round(payout, payout if multiplier else 0, "win" if multiplier else "lose")

    if game == "crash" and round_state.get("phase") == "active":
        elapsed = max(0, time.time() - round_state["started_at"])
        current = math.exp(min(10, elapsed * round_state["growth_rate"]))
        if current >= round_state["crash_point"]:
            round_state["phase"] = "over"
            return round_state, {"crashed": True, "multiplier": round_state["crash_point"], "phase": "over"}, finish_round()
        if action == "status":
            return round_state, {"crashed": False, "multiplier": current, "phase": "active"}, None
        if action != "cashout":
            raise ValueError("Invalid crash action")
        if current < 1.10:
            raise ValueError("Вывод доступен начиная с ×1,10")
        round_state["phase"] = "over"
        payout = money_product(bet, current)
        return round_state, {"crashed": False, "multiplier": current, "phase": "over"}, finish_round(payout, payout, "win")

    raise ValueError("No active round or incompatible action")

"""Generate the SYNTHETIC labelled benchmark (AIMW-Synth) used in the revision.

!!! SYNTHETIC DATA — NOT REAL-WORLD EVIDENCE !!!
Every item is generated from hand-written templates with a fixed random seed.
The label of each item is fixed *by construction* (the template family it is
drawn from), so labels are independent of the LLM judge and of the scoring
engine — this removes the circularity criticised by R1/R2 for this corpus.
It does NOT measure real-world accuracy: the templates were written by the
system authors (who know the indicator catalogue), the language is cleaner
than real social-media speech, and the class balance is artificial.  Use it
as a controlled functional test of the rules, thresholds and ablations; real
detection performance must come from the independently annotated real corpus
(see REVISION/annotation/).

Families (label by construction)
--------------------------------
Scam (label=1)
  S1 crypto doubling giveaway          S2 trading-signal VIP group
  S3 HYIP / daily-return platform      S4 MLM / referral recruitment
  S5 betting / casino "sure win"       S6 payment-phone "compensation" fraud (RU/KZ)
  S7 EVASIVE scam: no catalogue keywords (paraphrased, hard positives)
  S8 ADVERSARIAL scam wrapped in disclaimers / awareness phrases (gaming test)
Legitimate (label=0)
  L1 scam-awareness journalism QUOTING scam wallets/handles (hard negative)
  L2 crypto how-to tutorial showing example / placeholder addresses (hard negative)
  L3 personal-finance education with risk disclosure
  L4 ordinary sponsor read with a promo code (hard negative)
  L5 non-financial content (cooking, sport, travel)
  L6 market news / regulation report

Usage:  python scripts/revision/synth_corpus.py --out data/revision/synth_corpus.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

SEED = 20261107

# ── valid-checksum wallet generators (so promoter wallets are realistic) ─────
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _b58enc(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + out


def btc_legacy(rng: random.Random) -> str:
    payload = b"\x00" + bytes(rng.getrandbits(8) for _ in range(20))
    chk = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _b58enc(payload + chk)


def tron(rng: random.Random) -> str:
    payload = b"\x41" + bytes(rng.getrandbits(8) for _ in range(20))
    chk = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _b58enc(payload + chk)


def _polymod(values: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def bech32(rng: random.Random) -> str:
    hrp = "bc"
    data = [0] + [rng.randrange(32) for _ in range(32)]
    values = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + data
    pm = _polymod(values + [0] * 6) ^ 1
    chk = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_BECH[d] for d in data + chk)


def wallet(rng: random.Random) -> str:
    return rng.choice([btc_legacy, tron, bech32])(rng)


def handle(rng: random.Random) -> str:
    a = rng.choice(["crypto", "profit", "signal", "rich", "wealth", "trade", "invest", "moon"])
    b = rng.choice(["king", "master", "club", "vip", "pro", "boss", "team", "hub"])
    return f"@{a}_{b}{rng.randint(10, 999)}"


def tlink(rng: random.Random) -> str:
    return "t.me/" + handle(rng)[1:]


def phone(rng: random.Random) -> str:
    return f"+7 7{rng.randint(0, 9)}{rng.randint(0, 9)} {rng.randint(100, 999)} {rng.randint(10, 99)} {rng.randint(10, 99)}"


def pct(rng: random.Random) -> int:
    return rng.choice([3, 5, 7, 10, 12, 15, 20, 30])


C = random.Random  # alias for type hints


# ── template families ─────────────────────────────────────────────────────────
# Each returns (speech_sentences, ocr_lines). Placeholders filled per item.

def s1(r: C):
    w = wallet(r); coin = r.choice(["BTC", "ETH", "USDT"])
    sp = [
        r.choice([f"Hi everyone, to celebrate our launch we are giving back to the community.",
                  f"This is an official {coin} giveaway event, only for the next hour.",
                  "I am giving away crypto to my followers today."]),
        r.choice([f"Send any amount of {coin} to my wallet {w} and I will send double back.",
                  f"Send 0.1 {coin} to the address {w} and receive 0.2 back instantly.",
                  f"Deposit to {w} and get two times your {coin} back."]),
        r.choice(["Hurry, the event ends soon.", "Only the first one thousand participants qualify.",
                  "Don't miss this chance, it ends today."]),
    ]
    ocr = [f"SEND {coin} TO {w}", r.choice(["2X GIVEAWAY", "DOUBLE YOUR CRYPTO", "x2 BONUS - LIMITED TIME"])]
    return sp, ocr


def s2(r: C):
    p = pct(r); l = tlink(r)
    sp = [
        r.choice(["My VIP signals group made huge gains again this week.",
                  "Our trading signals are the most accurate on the market.",
                  "Stop losing money and follow our futures signals."]),
        r.choice([f"Guaranteed profit of {p}% daily with zero risk.",
                  f"We guarantee {p}% per day, every single day, no losses.",
                  f"You will make {p}% daily, it is risk free."]),
        r.choice([f"Join our telegram channel {l} today.", f"Subscribe at {l}, only fifty places left.",
                  f"Click the link {l} and join the VIP group now."]),
    ]
    ocr = [f"{p}% DAILY PROFIT", f"JOIN {l}"]
    return sp, ocr


def s3(r: C):
    p = pct(r)
    sp = [
        r.choice(["This new investment platform pays out every day.",
                  "I found a platform that gives passive income while you sleep.",
                  "Let me show you how I earn money every day without working."]),
        r.choice([f"Invest one hundred dollars and receive {p}% per day.",
                  f"The platform pays {p}% daily returns, guaranteed return on every deposit.",
                  f"Your deposit grows {p}% a day, withdraw anytime."]),
        r.choice(["Invite friends and earn per referral, the more people the more you earn.",
                  "Use my referral link to get a bonus.", "Register with my link below and start today."]),
    ]
    ocr = [f"+{p}% PER DAY", r.choice(["PASSIVE INCOME", "WITHDRAW ANYTIME", "MIN DEPOSIT $50"])]
    return sp, ocr


def s4(r: C):
    code = f"invite: {r.choice(['GOLD', 'RICH', 'TEAM', 'LEAD'])}{r.randint(100, 9999)}"
    sp = [
        r.choice(["Our business opportunity changed my life.", "I quit my job thanks to this team.",
                  "Become a partner and build your own team."]),
        r.choice(["You earn a bonus for every person you bring, and from everyone they bring.",
                  "Invite friends and earn per referral at every level of your team.",
                  "Recruit three people and your income starts flowing automatically."]),
        f"Sign up with my code {code} today.",
    ]
    ocr = [f"CODE {code}", r.choice(["EARN FROM YOUR TEAM", "PASSIVE INCOME", "BE YOUR OWN BOSS"])]
    return sp, ocr


def s5(r: C):
    code = f"promo: WIN{r.randint(100, 9999)}"
    sp = [
        r.choice(["I found a betting strategy that never loses.", "This casino app pays out every time.",
                  "My football predictions are one hundred percent sure."]),
        r.choice(["Bet with my system and get a guaranteed win.",
                  "You can make five hundred dollars a day from the casino, guaranteed profit.",
                  "Sports betting income every day, no risk."]),
        f"Register now and use {code} for a deposit bonus.",
    ]
    ocr = [f"USE {code}", r.choice(["100% WIN", "SURE BET", "CASINO BONUS 200%"])]
    return sp, ocr


def s6(r: C):
    ph = phone(r)
    sp = [
        r.choice(["Внимание! Всем гражданам положена компенсация от государства.",
                  "Вам начислена выплата, нужно только подтвердить данные.",
                  "Срочно! Ваш счет заблокирован, нужна оплата комиссии."]),
        r.choice([f"Переведи комиссию на каспи {ph} и получи деньги сегодня.",
                  f"Переводите 5000 тенге на каспи {ph}, после этого выплата придет.",
                  f"Оплата через Kaspi на номер {ph}, гарантированная выплата."]),
        r.choice(["Предложение действует только сегодня.", "Пиши в телеграм, места ограничены."]),
    ]
    ocr = [f"KASPI {ph}", r.choice(["КОМПЕНСАЦИЯ 150 000 ТГ", "ВЫПЛАТА СЕГОДНЯ"])]
    return sp, ocr


def s7(r: C):
    """Evasive scams: avoid catalogue phrases; paraphrase the hook."""
    w = wallet(r) if r.random() < 0.4 else None
    h = handle(r)
    sp = [
        r.choice(["Last month my students turned five hundred dollars into eight thousand.",
                  "People who copied my moves tripled their deposit in under two weeks.",
                  "I can't show everything on here, the algorithm deletes my videos."]),
        r.choice(["I only take a few new people each month because I personally manage the money.",
                  "You give me the capital, my team handles the trades, you just collect the payouts.",
                  "My method has not had a single losing week this year."]),
        (f"Transfer your starting amount to {w} and message me the receipt." if w else
         f"Message {h} with the word START and I'll walk you through it."),
    ]
    ocr = [r.choice(["$500 -> $8,000", "MY STUDENTS' RESULTS", "LIMITED SPOTS"]),
           (f"{w}" if w else f"DM {h}")]
    return sp, ocr


def l1(r: C):
    w = wallet(r); h = handle(r)
    sp = [
        r.choice(["Scam alert: in this video we expose a fake giveaway that is spreading on YouTube.",
                  "This is an investigative report on a crypto fraud network.",
                  "I investigated a channel that promised guaranteed profit to its viewers."]),
        r.choice([f"The scammers asked victims to send bitcoin to the address {w}. Do not send anything to it.",
                  f"Victims sent their savings to {w}, and the money was never returned.",
                  f"According to the police, the wallet {w} was used by the fraudsters."]),
        r.choice([f"The account {h} is fake, report it if you see it.",
                  "Remember: nobody gives away free crypto. Protect yourself.",
                  "Red flags include promises of guaranteed returns and pressure to act fast."]),
    ]
    ocr = [r.choice(["SCAM ALERT", "FRAUD WARNING", "DO NOT SEND"]), f"SCAM WALLET: {w}"]
    return sp, ocr


def l2(r: C):
    real = r.random() < 0.5
    w = wallet(r) if real else "bc1q" + "x" * 38
    sp = [
        r.choice(["In this tutorial I'll show you how to set up a hardware wallet.",
                  "Today we learn how a bitcoin address works and how to check it.",
                  "Let's go through how to receive crypto safely for the first time."]),
        r.choice([f"For example, an address looks like this: {w}. Yours will be different.",
                  f"Here is a sample address, {w}, just to show the format.",
                  f"Always double check the first and last characters, like in {w}."]),
        r.choice(["Never share your seed phrase with anyone.", "Take your time and test with a small amount first.",
                  "This is for educational purposes only."]),
    ]
    ocr = ["HOW TO RECEIVE CRYPTO", f"EXAMPLE: {w}"]
    return sp, ocr


def l3(r: C):
    sp = [
        r.choice(["Let's talk about index funds and why they are popular with beginners.",
                  "What is an emergency fund and how big should it be?",
                  "Today I explain compound interest with a simple example."]),
        r.choice(["Historically the market returned around seven percent a year on average, but some years were negative.",
                  "There is no guaranteed return in investing; you can lose money.",
                  "Past results do not guarantee future returns, so diversify."]),
        r.choice(["This is not financial advice, do your own research.",
                  "Talk to a licensed advisor before making big decisions.",
                  "Investing involves risk, capital at risk."]),
    ]
    ocr = [r.choice(["INVESTING 101", "COMPOUND INTEREST EXPLAINED", "EMERGENCY FUND"]), "NOT FINANCIAL ADVICE"]
    return sp, ocr


def l4(r: C):
    code = f"promo: {r.choice(['SAVE', 'TECH', 'COOK', 'FIT'])}{r.randint(10, 99)}"
    brand = r.choice(["a VPN service", "a meal kit company", "a language learning app", "a password manager"])
    sp = [
        f"This video is sponsored by {brand}.",
        r.choice(["I've been using it for months and it works well for me.",
                  "It's useful if you travel a lot.", "They have a free trial so you can test it."]),
        f"Use {code} at checkout for ten percent off your first month.",
    ]
    ocr = [f"{code}", "SPONSORED"]
    return sp, ocr


def l5(r: C):
    topic = r.choice(["cook", "sport", "travel"])
    if topic == "cook":
        sp = ["Today we are making a quick chocolate cake in a mug.",
              "Mix flour, sugar, cocoa and one egg, then microwave for ninety seconds.",
              "Add some whipped cream on top and enjoy."]
        ocr = ["MUG CAKE IN 2 MINUTES", "90 SECONDS"]
    elif topic == "sport":
        sp = ["What a goal in the final minute of the match.",
              "He has scored in five games in a row now.",
              "The team moves up to second place in the table."]
        ocr = ["GOAL!", "90+2'"]
    else:
        sp = ["We arrived in Almaty early in the morning.",
              "The mountains are only forty minutes from the city center.",
              "Next we are going to try the famous apples at the market."]
        ocr = ["ALMATY VLOG", "DAY 1"]
    return sp, ocr


def l6(r: C):
    p = pct(r)
    sp = [
        r.choice([f"Bitcoin fell {p}% this week after new regulation was announced.",
                  f"The central bank kept the base rate unchanged, markets moved {p}% in response.",
                  "Regulators issued a warning about unlicensed crypto exchanges."]),
        r.choice(["Analysts are divided on what comes next.",
                  "Experts say volatility is likely to remain high.",
                  "Investors are advised to be cautious."]),
        r.choice(["We will keep following this story.", "More details in our evening news.",
                  "That's all for today's market update."]),
    ]
    ocr = [r.choice(["MARKET UPDATE", "BREAKING NEWS", "CRYPTO NEWS"]), f"BTC -{p}%"]
    return sp, ocr


def s8(r: C):
    """ADVERSARIAL scam: a real solicitation wrapped in disclaimers / awareness
    language to game the mitigating signals (tests Rules A and B)."""
    sp, ocr = r.choice([s1, s2, s3])(r)
    wrap_pre = r.choice(["Scam alert! Protect yourself from fake projects.",
                         "This is for educational purposes only, not financial advice.",
                         "Red flags to watch out for, stay safe out there."])
    wrap_post = r.choice(["Not financial advice, do your own research.",
                          "Remember, how to avoid scams: only trust verified channels like mine.",
                          "Capital at risk. Educational purposes only."])
    return [wrap_pre] + sp + [wrap_post], ocr + ["NOT FINANCIAL ADVICE"]


FAMILIES = {
    "S1_giveaway": (1, s1, False), "S2_signals": (1, s2, False), "S3_hyip": (1, s3, False),
    "S4_mlm": (1, s4, False), "S5_betting": (1, s5, False), "S6_payment_phone_ru": (1, s6, False),
    "S7_evasive": (1, s7, True),
    "L1_journalism_quotes_wallet": (0, l1, True), "L2_tutorial_example_address": (0, l2, True),
    "L3_finance_education": (0, l3, False), "L4_sponsor_promo_code": (0, l4, True),
    "L5_non_financial": (0, l5, False), "L6_market_news": (0, l6, False),
    # appended last so the random stream (and every item above) is unchanged
    "S8_adversarial_disclaimer_wrapped": (1, s8, True),
}


def generate(n_per_family: int = 24, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    items: list[dict] = []
    for fam, (label, fn, hard) in FAMILIES.items():
        for i in range(n_per_family):
            sp, ocr = fn(rng)
            # Modality condition: 2/3 of items carry on-screen text, 1/3 are
            # speech-only (talking-head style) — exercises the single-source rule.
            has_ocr = (i % 3) != 2
            items.append({
                "id": f"{fam}-{i:03d}",
                "family": fam,
                "label": label,
                "hard": hard,
                "language": "ru" if fam.endswith("_ru") else "en",
                "has_ocr": has_ocr,
                "speech": [[float(4 * k), s] for k, s in enumerate(sp)],
                "ocr": [[float(4 * k + 1), o] for k, o in enumerate(ocr)] if has_ocr else [],
                "synthetic": True,
            })
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/revision/synth_corpus.jsonl")
    ap.add_argument("--n", type=int, default=24, help="items per family")
    args = ap.parse_args()
    items = generate(args.n)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    pos = sum(i["label"] for i in items)
    print(f"wrote {len(items)} SYNTHETIC items ({pos} scam / {len(items) - pos} legit) -> {out}")


if __name__ == "__main__":
    main()

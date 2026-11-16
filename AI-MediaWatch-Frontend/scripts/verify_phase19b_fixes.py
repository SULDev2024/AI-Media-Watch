"""Sanity check for the Phase 19B remediation edits.

Verifies (a) signals.yaml parses, (b) all new regex patterns compile, (c) the
new patterns actually match the FN transcript snippets from the baseline, (d)
the validator funnel-entity gate behaves as designed.
"""
from __future__ import annotations

import re
import yaml
from aimw.core.schema import EvidencePackage, EvidencePiece, ExtractedEntities
from aimw.scoring.discounts import Discount, discount_is_valid


def main() -> None:
    spec = yaml.safe_load(open("/app/config/signals.yaml"))
    print(f"signals.yaml: {len(spec['indicators'])} indicators")

    # Pull the regex lists from the three signals we touched
    targets = {"investment_promise", "passive_income", "guaranteed_profit"}
    new_keyword_set = set()
    for ind in spec["indicators"]:
        if ind["id"] == "trading_bot_promo":
            new_keyword_set = set(ind.get("match", {}).get("keywords", []))
        if ind["id"] not in targets:
            continue
        for r in ind.get("match", {}).get("regex", []):
            re.compile(r)  # raises if broken
    print("all regex patterns compile")

    # The FN snippets we are targeting (real strings from the baseline report)
    cases = [
        ("flip $100 to $5000", "investment_promise"),
        ("flip $10 to $100", "investment_promise"),
        ("turn $10 into $11,421", "investment_promise"),
        ("$10 to $11,421", "investment_promise"),
        ("Earn Up to $1,000 a day", "passive_income"),
        ("$1,000 daily", "passive_income"),
        ("$1000 per day", "passive_income"),
        ("$48 a day", "passive_income"),
    ]

    def fires(text: str, indicator: str) -> bool:
        for ind in spec["indicators"]:
            if ind["id"] != indicator:
                continue
            for kw in ind.get("match", {}).get("keywords", []):
                if kw.lower() in text.lower():
                    return True
            for r in ind.get("match", {}).get("regex", []):
                if re.search(r, text, re.IGNORECASE):
                    return True
        return False

    print("\nFN snippet coverage check:")
    for text, indicator in cases:
        ok = fires(text, indicator)
        flag = "OK " if ok else "MISS"
        print(f"  [{flag}] {indicator:22s}  '{text}'")

    new_words = {"telegram bot", "join my telegram", "vip signals", "chatgpt bot"}
    have = new_words & new_keyword_set
    miss = new_words - new_keyword_set
    print(f"\ntrading_bot_promo new keywords present: {sorted(have)}")
    if miss:
        print(f"  MISSING (unexpected): {sorted(miss)}")

    # Validator funnel-entity gate — TED-Ed-shaped (no funnel) must still
    # validate; "buys downline members"-shaped (also no funnel here) also still
    # validates per the deliberate Phase 19B scoping; only a telegram/wallet/
    # phone entity should block.
    import datetime as dt
    NOW = dt.datetime.now(dt.UTC)

    def pkg_with(entities: ExtractedEntities) -> EvidencePackage:
        return EvidencePackage(
            report_id="t1", video_id="v1", platform="youtube",
            url="https://yt/v1", collected_at=NOW, processed_at=NOW,
            evidence=[
                EvidencePiece(
                    indicator_type="pyramid_recruit",
                    source="speech",
                    polarity="incriminating",
                    strength="medium",
                    raw_value="recruit two more",
                    content="pyramid_recruit detected in speech: 'and recruit two more members'",
                    timestamp=10.0,
                    recovery_method="raw",
                )
            ],
            entities=entities,
        )

    d = Discount(kind="quote_not_offer", piece_indicator_type="pyramid_recruit")
    print("\nvalidator funnel-entity gate:")
    cases2 = [
        ("empty entities (TED-Ed-like)", ExtractedEntities()),
        ("telegram_handles present", ExtractedEntities(telegram_handles=["@scam"])),
        ("crypto_wallets present", ExtractedEntities(crypto_wallets=["bc1qxxx"])),
        ("payment_phones present", ExtractedEntities(payment_phones=["+15551234"])),
        ("referral_codes only (should still validate)", ExtractedEntities(referral_codes=["promo code"])),
        ("websites only (should still validate)", ExtractedEntities(websites=["example.com"])),
    ]
    for label, ents in cases2:
        ok = discount_is_valid(d, pkg_with(ents))
        print(f"  validate={ok}   {label}")


if __name__ == "__main__":
    main()

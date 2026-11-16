"""Regression tests for the reviewer-driven scoring revision.

R1/R2: single-source ceiling must sit strictly below the HIGH threshold.
R2:    payment rails reproduced in journalism/education must not be penalised
       as if the promoter offered them; payment channels are checksum-verified.
"""

from __future__ import annotations

import pytest

from aimw.entities.linkage import classify_value, verify_wallet_format
from aimw.scoring import engine
from aimw.scoring.rules import single_source_ceiling
from aimw.validation.offline import score_text

GENESIS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # valid Base58Check
BECH32 = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"  # valid bech32


# ── R1/R2: threshold / ceiling consistency ──────────────────────────────────


def test_deployed_thresholds_are_consistent():
    t = engine._load_thresholds()
    engine.validate_thresholds(t)
    assert single_source_ceiling(t["high"]) < t["high"]


def test_thresholds_loaded_from_package_config_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine._invalidate_thresholds_cache()
    assert engine._load_thresholds()["high"] == pytest.approx(0.47395)


@pytest.mark.parametrize("bad", [
    {"low": 0.1, "medium": 0.5, "high": 0.47, "critical": 0.8},   # medium > high
    {"low": 0.1, "medium": 0.47, "high": 0.475, "critical": 0.8},  # ceiling < medium
])
def test_inconsistent_thresholds_are_rejected(bad):
    with pytest.raises(ValueError):
        engine.validate_thresholds(bad)


@pytest.mark.parametrize("high", [0.40, 0.47395, 0.55, 0.60, 0.70])
def test_single_source_never_reaches_high_for_any_threshold(high):
    t = {"low": 0.1, "medium": 0.30, "high": high, "critical": 0.8}
    speech = [
        (0.0, "Guaranteed profit, no risk, 5% daily returns!"),
        (6.0, "Invite friends and earn per referral, join the passive income program"),
        (12.0, f"Send BTC to my wallet {GENESIS} and receive double back"),
    ]
    b = score_text(speech, thresholds=t)
    assert b.level not in ("HIGH", "CRITICAL")
    assert b.final_score < high


def test_two_independent_modalities_can_reach_high():
    speech = [(0.0, "Guaranteed profit, no risk, 5% daily returns!"),
              (6.0, f"Send BTC to my wallet {GENESIS} now")]
    ocr = [(3.0, "GUARANTEED PROFIT 5% DAILY - NO RISK")]
    b = score_text(speech, ocr)
    assert b.level in ("HIGH", "CRITICAL")
    assert not b.single_source_ceiling_applied


def test_entity_pieces_do_not_count_as_independent_source():
    speech = [(0.0, f"Guaranteed profit! Send to my wallet {GENESIS}")]
    b = score_text(speech)
    sources = {p.source for p in b.per_piece if p.polarity == "incriminating"}
    assert sources == {"speech", "entity"}
    assert b.final_score <= single_source_ceiling(engine._load_thresholds()["high"])


# ── R2: payment-channel verification ───────────────────────────────────────


def test_wallet_checksums():
    assert verify_wallet_format(GENESIS) == "valid"
    assert verify_wallet_format(GENESIS[:-1] + "b") == "invalid"
    assert verify_wallet_format(BECH32) == "valid"
    assert verify_wallet_format(BECH32[:-1] + "x") == "invalid"
    assert verify_wallet_format("0x" + "ab" * 20) == "format_only"


@pytest.mark.parametrize("text,expected", [
    (f"Send 0.1 BTC to my wallet {GENESIS} and get 0.2 back", "promoter"),
    (f"Deposit to {GENESIS} today", "promoter"),
    (f"Warning: the scammers used the wallet {GENESIS}. Do not send anything.", "reported"),
    (f"Never send money to {GENESIS}", "reported"),
    (f"Victims sent their savings to {GENESIS}", "reported"),
    (f"The address {GENESIS} received two million dollars", "unlinked"),
])
def test_promoter_linkage(text, expected):
    assert classify_value(GENESIS, [text], is_wallet=True) == expected


def test_invalid_checksum_wallet_is_never_promoter():
    fake = GENESIS[:-1] + "b"
    assert classify_value(fake, [f"Send BTC to my wallet {fake}"], is_wallet=True) != "promoter"


# ── R2: journalism / education reproducing wallets is not penalised ─────────


def test_journalism_quoting_wallet_is_not_high():
    speech = [
        (0.0, "Scam alert. In this investigative report we expose fraud on YouTube."),
        (6.0, f"The scammers asked victims to send bitcoin to {GENESIS}. Do not send anything."),
        (12.0, "Victims lost thousands after being promised guaranteed profit."),
    ]
    ocr = [(5.0, f"SCAM WALLET: {GENESIS} - DO NOT SEND")]
    b = score_text(speech, ocr)
    assert not b.applied_entity_gate
    assert b.level in ("CLEAN", "LOW", "MEDIUM")
    assert all(p.indicator_type != "payment_wallet_disclosed" for p in b.per_piece)


def test_promoter_wallet_still_fires_gate():
    speech = [(0.0, "Scam alert! Not financial advice."),
              (5.0, f"Send 1 BTC to my wallet {GENESIS} and get 2 BTC back, guaranteed profit")]
    ocr = [(4.0, f"SEND TO {GENESIS} - GUARANTEED PROFIT")]
    b = score_text(speech, ocr)
    assert b.applied_entity_gate
    assert b.level in ("HIGH", "CRITICAL")


def test_ablation_names_validated():
    with pytest.raises(ValueError):
        score_text([(0.0, "hello")], ablate=frozenset({"no_such_rule"}))


def test_plain_invite_phrase_is_not_a_referral_code():
    from aimw.entities.patterns import extract_referrals
    assert extract_referrals("Invite friends and earn per referral") == []
    assert extract_referrals("Sign up with invite: LEAD6348") == ["invite: LEAD6348"]

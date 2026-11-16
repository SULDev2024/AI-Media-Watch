# ruff: noqa: E501  (long literal test sentences)
"""Measured evasion benchmark — keyword baseline vs. the AIMW deterministic layer.

Runs a controlled, hand-written set of scam-promotion and benign (journalism /
education) utterances through:

  * the naive keyword baseline  (aimw.adversarial.baseline)
  * the AIMW deterministic layer (entity extraction -> signal tagging -> scoring)

for the original text and every evasion in ``aimw.adversarial.evasion``.
With ``--judge`` it also runs the LLM intent judge on every variant, using the
AIMW_LLM_* settings in .env (the self-hosted Ollama / qwen2.5vl server).

Usage:  .venv/bin/python scripts/evasion_benchmark.py [--judge] [--json out.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict

from aimw.adversarial import baseline, evasion
from aimw.core.schema.evidence import EvidencePackage
from aimw.entities.extractor import extract
from aimw.extraction.whisper.models import Segment, Transcript
from aimw.scoring.engine import score
from aimw.scoring.signals import tag

_TS = dt.datetime(2026, 9, 29, tzinfo=dt.UTC)
_REPORTED = {"MEDIUM", "HIGH", "CRITICAL"}

# Public, well-known addresses (checksum-valid) used only as test fixtures.
BTC = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
TRX = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
ETH = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"

SCAM_EN = [
    f"Guaranteed profit of 5% every day. Send USDT to {TRX} and watch your money grow.",
    "Join my VIP signals channel t.me/profit_kings_vip, passive income with no risk at all.",
    "Double your money in 24 hours, write to @crypto_boss_admin to get started today.",
    f"Risk free investment, 100% profit guaranteed. Deposit to {BTC} now.",
    "Invite your friends and earn a referral bonus on every deposit, use code RICH2026.",
    "This platform pays daily payouts, guaranteed return of 30% per week, link in bio.",
    "Get rich fast with our trading bot, financial freedom in one month, DM @bot_signals_pro.",
    f"Send any amount of ETH to {ETH} and we send back double, limited time giveaway.",
    "Our casino strategy never loses, sign up with my referral link and win every day.",
    "Passive income from staking, no risk, withdraw anytime, join t.me/stake_rich_club.",
    "Last chance, only 10 spots left in the investment pool, guaranteed profit for members.",
    "Bring three friends and receive 50 dollars for each one, this is financial freedom.",
    f"Betting tips with 100% win rate, pay the subscription to {TRX}.",
    "Earn 1000 dollars a day from home, crypto signals every morning, contact @earn_daily_kz.",
    "No experience needed, guaranteed return on your investment, message the admin on Telegram.",
]
SCAM_RU = [
    f"Гарантированный доход 5% в день, переводите USDT на {TRX}.",
    "Пассивный доход без риска, подписывайтесь на t.me/dohod_kz_vip.",
    "Удвоим ваши деньги за сутки, пишите администратору @invest_boss_kz.",
    "Приглашай друзей и получай реферальный бонус с каждого депозита, код BONUS777.",
    "Ежедневные выплаты и гарантированная прибыль, ссылка в описании.",
    f"Отправьте биткоин на {BTC} и получите вдвое больше.",
    "Крипто сигналы каждый день, заработок от 500 долларов, пишите @signals_ru_pro.",
    "Беспроигрышная стратегия для казино, регистрируйся по моей ссылке.",
    "Инвестиции без риска, доход 30% в неделю, осталось всего 10 мест.",
    "Ставки на спорт с гарантией выигрыша, оплата подписки на кошелёк в профиле.",
    "Пассивный доход от стейкинга, вывод в любое время, вступай в t.me/stake_kz.",
    "Заработок из дома без опыта, гарантированный результат, пишите в Телеграм.",
    "Приведи трёх друзей и получи бонус за каждого, это твоя финансовая свобода.",
    f"Вложите от 100 долларов и получайте ежедневные выплаты, кошелёк {TRX}.",
    "Торговый бот приносит 100% прибыли, доступ только через @bot_admin_kz.",
]
BENIGN_EN = [
    "In this investigation we explain how fake crypto platforms promise guaranteed profit and steal deposits.",
    "Never trust anyone who offers passive income with no risk, that is the classic sign of a Ponzi scheme.",
    "Today we look at the history of pyramid schemes and why regulators shut them down.",
    "Financial education: diversification lowers risk, but no investment is ever risk free.",
    "Viewers sent us messages from Telegram channels offering to double their money, here is why it is a scam.",
    "The regulator warned about unlicensed brokers that advertise guaranteed returns on social media.",
    "Satire: I invested my lunch money in a coin named after my cat and lost everything.",
    "How referral schemes work and why recruiting friends is the engine of every pyramid.",
    "Court sentences organisers of a crypto Ponzi scheme that promised daily payouts.",
    "Beginner guide to index funds: expect about seven percent a year over the long run.",
    "If a video promises financial freedom in a month, report it to the platform.",
    "We tested five trading bots and none of them delivered the advertised profits.",
    "Casino marketing uses the illusion of control, a psychologist explains the tricks.",
    "Journalists traced the wallet of a giveaway scam and found stolen funds from victims.",
    "Licensed adviser answers questions about retirement savings and pension funds.",
]
BENIGN_RU = [
    "В этом расследовании мы показываем, как мошенники обещают гарантированный доход и крадут деньги.",
    "Никогда не верьте тем, кто предлагает пассивный доход без риска, это признак пирамиды.",
    "Сегодня разбираем историю финансовых пирамид и почему их закрывают.",
    "Финансовая грамотность: диверсификация снижает риск, но инвестиций без риска не бывает.",
    "Зрители присылают сообщения из Телеграм каналов с предложением удвоить деньги, объясняем, почему это обман.",
    "Регулятор предупредил о нелицензированных брокерах, которые рекламируют гарантированную доходность.",
    "Сатира: я вложил деньги на обед в монету с именем моего кота и всё потерял.",
    "Как работают реферальные схемы и почему привлечение друзей двигатель любой пирамиды.",
    "Суд вынес приговор организаторам криптопирамиды, обещавшей ежедневные выплаты.",
    "Инструкция для начинающих по индексным фондам и долгосрочным инвестициям.",
    "Если видео обещает финансовую свободу за месяц, пожалуйтесь на него платформе.",
    "Мы проверили пять торговых ботов, и ни один не принёс обещанной прибыли.",
    "Психолог объясняет, как реклама казино создаёт иллюзию контроля.",
    "Журналисты отследили кошелёк мошенников и нашли деньги пострадавших.",
    "Лицензированный консультант отвечает на вопросы о пенсионных накоплениях.",
]

DATASET = (
    [("scam", "en", t) for t in SCAM_EN]
    + [("scam", "ru", t) for t in SCAM_RU]
    + [("benign", "en", t) for t in BENIGN_EN]
    + [("benign", "ru", t) for t in BENIGN_RU]
)


def aimw_layer(text: str, idx: int) -> dict:
    tr = Transcript(
        engine_version="bench",
        model="none",
        device="cpu",
        compute_type="none",
        source_file_sha256="0" * 64,
        video_id=f"ev{idx}",
        language_detected="auto",
        segments=[Segment(start=0.0, end=5.0, text=text)],
        generated_at=_TS,
    )
    entities, spans = extract(tr, None)
    pieces = tag(spans, entities, None, tr)
    pkg = EvidencePackage(
        report_id=f"ev{idx}",
        video_id=f"ev{idx}",
        platform="youtube",
        url=f"https://example.org/{idx}",
        collected_at=_TS,
        processed_at=_TS,
        evidence=pieces,
        entities=entities,
    )
    br = score(pkg)
    incrim = [p for p in pieces if p.polarity == "incriminating"]
    n_ent = sum(len(v) for k, v in entities.model_dump().items() if isinstance(v, list))
    return {
        "signal": bool(incrim),
        "entities": n_ent,
        "level": br.level,
        "score": br.final_score,
        "pkg": pkg,
    }


class _NoCapUsage:
    """In-memory UsageTracker: the self-hosted server has no token budget."""

    async def remaining(self, date: dt.date, model: str, daily_cap: int) -> int:
        return daily_cap

    async def add(self, date: dt.date, model: str, tokens: int) -> None:
        return None


def make_judge():
    import asyncio

    from dotenv import load_dotenv

    load_dotenv()
    from aimw.core.config import get_settings
    from aimw.reasoning.client import build_chat_client
    from aimw.reasoning.judge import classify

    settings = get_settings()
    print(f"judge: {settings.resolved_llm_base_url} model={settings.resolved_llm_model}")
    client = build_chat_client(_NoCapUsage(), settings=settings)

    def judge(pkg: EvidencePackage, text: str) -> bool | None:
        try:
            verdict = asyncio.run(classify(pkg, text, client))
        except Exception as exc:  # report, don't abort a long run
            print(f"  judge error: {type(exc).__name__}: {exc}")
            return None
        return verdict.is_fraud_promotion

    return judge


def main() -> None:
    import logging

    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--judge", action="store_true", help="also run the LLM intent judge")
    args = ap.parse_args()
    judge = make_judge() if args.judge else None

    conds = ["original", "homoglyph", "spacing", "leetspeak", "zero_width"]
    # agg[cond][label][metric] -> count
    agg: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    rows = []
    for i, (label, lang, text) in enumerate(DATASET):
        variants = {"original": text, **evasion.mutate(text)}
        orig_entities = None
        for cond in conds:
            t = variants[cond]
            kw = baseline.classify(t)["flagged"]
            a = aimw_layer(t, i)
            pkg = a.pop("pkg")
            if judge is not None:
                a["judge"] = judge(pkg, t)
            if cond == "original":
                orig_entities = a["entities"]
            a_rep = a["level"] in _REPORTED
            for key in (label, f"{label}_{lang}"):
                g = agg[cond][key]
                g["n"] += 1
                g["kw"] += kw
                g["sig"] += a["signal"]
                g["rep"] += a_rep
                g["ent_orig"] += orig_entities or 0
                g["ent_kept"] += min(a["entities"], orig_entities or 0)
                if a.get("judge") is not None:
                    g["j_n"] += 1
                    g["judge"] += a["judge"]
            rows.append({"i": i, "label": label, "lang": lang, "cond": cond, "kw": kw, **a})

    def pct(a, b):
        return f"{100 * a / b:5.1f}%" if b else "   - "

    print(
        f"{'condition':<11} {'KW det(scam)':>13} {'AIMW sig(scam)':>15} {'AIMW rep(scam)':>15} "
        f"{'entities kept':>14} {'KW FP(benign)':>14} {'AIMW sig FP':>12} {'AIMW rep FP':>12}"
    )
    for cond in conds:
        s, b = agg[cond]["scam"], agg[cond]["benign"]
        print(
            f"{cond:<11} {pct(s['kw'], s['n']):>13} {pct(s['sig'], s['n']):>15} {pct(s['rep'], s['n']):>15} "
            f"{pct(s['ent_kept'], s['ent_orig']):>14} {pct(b['kw'], b['n']):>14} {pct(b['sig'], b['n']):>12} {pct(b['rep'], b['n']):>12}"
        )
    if judge is not None:
        print("\nLLM judge (is_fraud_promotion): scam detection / benign false flags")
        for cond in conds:
            s, b = agg[cond]["scam"], agg[cond]["benign"]
            print(
                f"{cond:<11} {pct(s['judge'], s['j_n'])} / {pct(b['judge'], b['j_n'])}"
                f"   (answered {s['j_n'] + b['j_n']}/{s['n'] + b['n']})"
            )
    print("\nby language (scam detection: KW / AIMW signal)")
    for cond in conds:
        parts = []
        for lang in ("en", "ru"):
            g = agg[cond][f"scam_{lang}"]
            parts.append(f"{lang}: {pct(g['kw'], g['n'])} / {pct(g['sig'], g['n'])}")
        print(f"{cond:<11} " + "   ".join(parts))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"rows": rows}, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

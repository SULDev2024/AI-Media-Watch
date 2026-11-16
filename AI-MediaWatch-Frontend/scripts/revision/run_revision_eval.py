"""Revision evaluation: baselines, ablations, sensitivity, CIs (reviewers R1/R2).

Everything here is deterministic and LLM-free.  Inputs:
  data/revision/synth_corpus.jsonl     SYNTHETIC text corpus (label by construction)
  data/revision/mm_extracted.jsonl     SYNTHETIC videos after real OCR (+ASR stand-in)
  data/revision/scores_v1*.json        pre-revision engine scores (score_corpus.py with v1 src)
Outputs (data/revision/results/):
  results.json, tables.md, *.png

Operating points (fixed BEFORE looking at results, i.e. not tuned on test data):
  ALERT   = level ∈ {HIGH, CRITICAL}  (score ≥ deployed HIGH threshold 0.47395)
  QUEUE   = level ∈ {MEDIUM, HIGH, CRITICAL} (score ≥ 0.35; analyst review queue)

Usage:  PYTHONPATH=src python scripts/revision/run_revision_eval.py
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("AIMW_LOG_LEVEL", "WARNING")
logging.disable(logging.INFO)

import numpy as np  # noqa: E402
import yaml  # noqa: E402

from aimw.scoring import engine  # noqa: E402
from aimw.scoring.weights import WEIGHT  # noqa: E402
from aimw.validation.offline import build_package  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "revision"
OUT = DATA / "results"
OUT.mkdir(parents=True, exist_ok=True)

T_DEPLOYED = engine._load_thresholds()
ALERT = {"HIGH", "CRITICAL"}
QUEUE = {"MEDIUM", "HIGH", "CRITICAL"}
RNG = np.random.default_rng(2026)


# ── metrics ────────────────────────────────────────────────────────────────

def prf(y, p):
    y, p = np.asarray(y), np.asarray(p)
    tp = int(((y == 1) & (p == 1)).sum()); fp = int(((y == 0) & (p == 1)).sum())
    fn = int(((y == 1) & (p == 0)).sum()); tn = int(((y == 0) & (p == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    acc = (tp + tn) / len(y)
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {"precision": prec, "recall": rec, "f1": f1, "accuracy": acc, "fpr": fpr,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def bootstrap_ci(y, p, n=2000):
    y, p = np.asarray(y), np.asarray(p)
    stats = defaultdict(list)
    for _ in range(n):
        idx = RNG.integers(0, len(y), len(y))
        m = prf(y[idx], p[idx])
        for k in ("precision", "recall", "f1", "fpr"):
            stats[k].append(m[k])
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in stats.items()}


def auc(y, s):
    y, s = np.asarray(y), np.asarray(s, dtype=float)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def summarize(name, y, pred, scores=None, ci=True):
    m = prf(y, pred)
    m["system"] = name
    if ci:
        m["ci95"] = bootstrap_ci(y, pred)
    if scores is not None:
        m["auc"] = auc(y, scores)
    return m


# ── baselines ──────────────────────────────────────────────────────────────

def item_text(it):
    return " ".join(s for _, s in it["speech"]) + " " + " ".join(s for _, s in it.get("ocr", []))


def catalogue_any_baseline(items):
    """B0: any incriminating keyword/regex of signals.yaml anywhere → scam."""
    cat = yaml.safe_load((ROOT / "config" / "signals.yaml").read_text(encoding="utf-8"))
    kws, pats = [], []
    for e in cat["indicators"]:
        if e["polarity"] != "incriminating" or e.get("requires"):
            continue
        kws += [str(k).lower() for k in e.get("match", {}).get("keywords", [])]
        pats += [re.compile(r, re.I | re.U) for r in e.get("match", {}).get("regex", [])]
    out = []
    for it in items:
        t = item_text(it).lower()
        hit = any(k in t for k in kws) or any(p.search(t) for p in pats)
        out.append(int(hit))
    return out


GENERIC_LEXICON = [
    "guarantee", "double", "giveaway", "risk free", "no risk", "send", "wallet", "profit",
    "passive income", "limited", "act now", "telegram", "dm ", "message me", "referral", "bonus",
    "deposit", "invest", "earn", "% daily", "per day", "перевод", "каспи", "выплат",
]


def generic_lexicon_baseline(items, k=2):
    """B1: ≥k hits from a generic consumer-protection scam lexicon (not the catalogue)."""
    out, cnt = [], []
    for it in items:
        t = item_text(it).lower()
        c = sum(1 for w in GENERIC_LEXICON if w in t)
        cnt.append(c)
        out.append(int(c >= k))
    return out, cnt


def tfidf_lr(items, scheme):
    """B2: TF-IDF(1-2gram)+LogReg; 'cv5' stratified 5-fold or 'lofo' leave-one-family-out."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold

    X = np.array([item_text(it) for it in items]); y = np.array([it["label"] for it in items])
    fam = np.array([it["family"] for it in items])
    pred = np.zeros(len(y), dtype=int); prob = np.zeros(len(y))
    if scheme == "cv5":
        splits = StratifiedKFold(5, shuffle=True, random_state=0).split(X, y)
    else:
        splits = [(np.where(fam != f)[0], np.where(fam == f)[0]) for f in sorted(set(fam))]
    for tr, te in splits:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        clf = LogisticRegression(max_iter=2000, C=4.0)
        clf.fit(vec.fit_transform(X[tr]), y[tr])
        prob[te] = clf.predict_proba(vec.transform(X[te]))[:, 1]
        pred[te] = (prob[te] >= 0.5).astype(int)
    return pred.tolist(), prob.tolist()


# ── engine helpers ─────────────────────────────────────────────────────────

def packages(items):
    return [build_package([tuple(s) for s in it["speech"]], [tuple(o) for o in it.get("ocr", [])],
                          video_id=it["id"]) for it in items]


def run_engine(pkgs, **kw):
    bs = [engine.score(p, **kw) for p in pkgs]
    return [b.final_score for b in bs], [b.level for b in bs]


def per_family(items, pred):
    rows = defaultdict(lambda: [0, 0])
    for it, p in zip(items, pred):
        rows[it["family"]][0] += p; rows[it["family"]][1] += 1
    return {f: {"flagged": a, "n": n, "rate": a / n} for f, (a, n) in sorted(rows.items())}


# ── main ───────────────────────────────────────────────────────────────────

def main():
    items = [json.loads(l) for l in (DATA / "synth_corpus.jsonl").read_text(encoding="utf-8").splitlines()]
    y = [it["label"] for it in items]
    res: dict = {"note": "SYNTHETIC benchmark (labels by construction). Not real-world accuracy.",
                 "n_items": len(items), "n_scam": int(sum(y)), "deployed_thresholds": T_DEPLOYED}

    pk = packages(items)
    s2, l2 = run_engine(pk)
    systems = []
    systems.append(summarize("AIMW v2 (revised) — ALERT (HIGH+)", y, [int(l in ALERT) for l in l2], s2))
    systems.append(summarize("AIMW v2 (revised) — QUEUE (MEDIUM+)", y, [int(l in QUEUE) for l in l2], s2))
    v1 = json.loads((DATA / "scores_v1.json").read_text())
    s1 = [v1[it["id"]]["score"] for it in items]; l1 = [v1[it["id"]]["level"] for it in items]
    systems.append(summarize("AIMW v1 (submitted) — ALERT (HIGH+)", y, [int(l in ALERT) for l in l1], s1))
    systems.append(summarize("AIMW v1 (submitted) — QUEUE (MEDIUM+)", y, [int(l in QUEUE) for l in l1], s1))
    b0 = catalogue_any_baseline(items)
    systems.append(summarize("B0 catalogue keyword-any (no weights/gates)", y, b0))
    b1, b1c = generic_lexicon_baseline(items)
    systems.append(summarize("B1 generic scam lexicon (≥2 hits)", y, b1, b1c))
    for scheme, label in (("cv5", "B2 TF-IDF+LogReg, 5-fold CV"), ("lofo", "B2 TF-IDF+LogReg, leave-one-family-out")):
        p, pr = tfidf_lr(items, scheme)
        systems.append(summarize(label, y, p, pr))
    # optional: LLM judge scores produced on the GPU machine by llm_judge_eval.py
    for mode in ("fast", "full"):
        f = DATA / f"llm_scores_{mode}.json"
        if not f.exists():
            continue
        llm = json.loads(f.read_text())
        idx = [i for i, it in enumerate(items) if it["id"] in llm and llm[it["id"]]["valid"]]
        if not idx:
            continue
        yy = [y[i] for i in idx]
        ls = [llm[items[i]["id"]]["risk_score"] for i in idx]
        lv2 = [l2[i] for i in idx]
        tag_ = f"[n={len(idx)}]"
        # same-subset references so the LLM rows are compared like for like
        systems.append(summarize(f"AIMW v2 — QUEUE (MEDIUM+), same subset {tag_}", yy, [int(l in QUEUE) for l in lv2],
                                 [s2[i] for i in idx]))
        systems.append(summarize(f"B1 generic scam lexicon, same subset {tag_}", yy, [b1[i] for i in idx]))
        fam_rates = {}
        for i, v in zip(idx, ls):
            f_ = items[i]["family"]; fam_rates.setdefault(f_, []).append(int(v >= 50))
        res[f"llm_{mode}_per_family_flag_rate"] = {f_: sum(v) / len(v) for f_, v in sorted(fam_rates.items())}
        systems.append(summarize(f"LLM judge ({mode}) score≥50 {tag_}", yy, [int(v >= 50) for v in ls], ls))
        systems.append(summarize(f"LLM judge ({mode}) score≥70 {tag_}", yy, [int(v >= 70) for v in ls], ls))
        systems.append(summarize(f"Fused: LLM≥50 AND engine QUEUE {tag_}", yy,
                                 [int(v >= 50 and l in QUEUE) for v, l in zip(ls, lv2)]))
        systems.append(summarize(f"Fused: LLM≥50 OR engine ALERT {tag_}", yy,
                                 [int(v >= 50 or l in ALERT) for v, l in zip(ls, lv2)]))
        res[f"llm_{mode}_invalid"] = sum(1 for it in items if it["id"] in llm and not llm[it["id"]]["valid"])
    res["systems"] = systems

    # hard subset + per family
    hard_idx = [i for i, it in enumerate(items) if it["hard"]]
    res["hard_subset"] = {
        "n": len(hard_idx),
        "v2_alert": prf([y[i] for i in hard_idx], [int(l2[i] in ALERT) for i in hard_idx]),
        "v1_alert": prf([y[i] for i in hard_idx], [int(l1[i] in ALERT) for i in hard_idx]),
        "v2_queue": prf([y[i] for i in hard_idx], [int(l2[i] in QUEUE) for i in hard_idx]),
        "v1_queue": prf([y[i] for i in hard_idx], [int(l1[i] in QUEUE) for i in hard_idx]),
    }
    res["per_family"] = {
        "v2_alert": per_family(items, [int(l in ALERT) for l in l2]),
        "v2_queue": per_family(items, [int(l in QUEUE) for l in l2]),
        "v1_alert": per_family(items, [int(l in ALERT) for l in l1]),
        "v1_queue": per_family(items, [int(l in QUEUE) for l in l1]),
    }

    # modality ablation (speech-only)
    sp_items = [{**it, "ocr": []} for it in items]
    ssp, lsp = run_engine(packages(sp_items))
    res["modality"] = {
        "speech+ocr": {"alert": prf(y, [int(l in ALERT) for l in l2]), "queue": prf(y, [int(l in QUEUE) for l in l2])},
        "speech_only": {"alert": prf(y, [int(l in ALERT) for l in lsp]), "queue": prf(y, [int(l in QUEUE) for l in lsp])},
    }

    # rule ablations
    abl = {}
    for rule in sorted(engine.ABLATABLE_RULES):
        sa, la = run_engine(pk, ablate=frozenset({rule}))
        abl[rule] = {"alert": prf(y, [int(l in ALERT) for l in la]), "queue": prf(y, [int(l in QUEUE) for l in la]),
                     "auc": auc(y, sa)}
    # payment-linkage ablation: treat every entity as promoter-linked (= v1 behaviour)
    pk_nolink = [p.model_copy(update={"entities": p.entities.model_copy(update={"payment_linkage": {}})}) for p in pk]
    sa, la = run_engine(pk_nolink)
    abl["payment_linkage"] = {"alert": prf(y, [int(l in ALERT) for l in la]),
                              "queue": prf(y, [int(l in QUEUE) for l in la]), "auc": auc(y, sa)}
    abl["_full_v2"] = {"alert": prf(y, [int(l in ALERT) for l in l2]), "queue": prf(y, [int(l in QUEUE) for l in l2]),
                       "auc": auc(y, s2)}
    res["ablations"] = abl

    # sensitivity 1: HIGH-threshold sweep (ceiling moves with it, by design)
    sweep = []
    for h in np.round(np.arange(0.36, 0.80, 0.02), 3):
        t = dict(T_DEPLOYED); t["high"] = float(h)
        try:
            engine.validate_thresholds(t)
        except ValueError:
            continue
        _, lv = run_engine(pk, thresholds=t)
        m = prf(y, [int(l in ALERT) for l in lv]); m["high"] = float(h)
        sweep.append(m)
    res["sensitivity_high_threshold"] = sweep

    # sensitivity 2: one-at-a-time weight ±20 %
    oat = []
    for key in WEIGHT:
        for f in (0.8, 1.2):
            w = dict(WEIGHT); w[key] = WEIGHT[key] * f
            _, lv = run_engine(pk, weights=w)
            m = prf(y, [int(l in ALERT) for l in lv]); mq = prf(y, [int(l in QUEUE) for l in lv])
            oat.append({"weight": f"{key[0]}/{key[1]}", "factor": f, "alert_f1": m["f1"], "queue_f1": mq["f1"],
                        "alert_fpr": m["fpr"], "alert_recall": m["recall"]})
    res["sensitivity_weights_oat"] = oat

    # sensitivity 3: Monte-Carlo joint perturbation U(0.8,1.2) of all six weights
    mc_alert, mc_queue = [], []
    rnd = random.Random(1)
    for _ in range(200):
        w = {k: v * rnd.uniform(0.8, 1.2) for k, v in WEIGHT.items()}
        _, lv = run_engine(pk, weights=w)
        mc_alert.append(prf(y, [int(l in ALERT) for l in lv])["f1"])
        mc_queue.append(prf(y, [int(l in QUEUE) for l in lv])["f1"])
    res["sensitivity_weights_mc"] = {
        "draws": 200,
        "alert_f1": {"mean": float(np.mean(mc_alert)), "p5": float(np.percentile(mc_alert, 5)), "p95": float(np.percentile(mc_alert, 95))},
        "queue_f1": {"mean": float(np.mean(mc_queue)), "p5": float(np.percentile(mc_queue, 5)), "p95": float(np.percentile(mc_queue, 95))},
    }

    # invariant check on every item: no single-modality package reaches HIGH
    viol = 0
    for p in pk:
        b = engine.score(p)
        mods = {pp.source for pp in b.per_piece if pp.polarity == "incriminating" and pp.applied_weight != 0 and pp.source in {"speech", "ocr", "vision", "network"}}
        if len(mods) <= 1 and b.level in ALERT:
            viol += 1
    res["invariant_single_source_high_violations"] = viol
    v1_viol = 0
    for it, lv in zip(items, l1):
        pcs = v1[it["id"]]["pieces"]
        mods = {s for _, s, w in pcs if w and w > 0 and s in {"speech", "ocr", "vision", "network"}}
        if len(mods) <= 1 and lv in ALERT:
            v1_viol += 1
    res["invariant_single_source_high_violations_v1"] = v1_viol

    # multimodal (rendered videos, real OCR)
    mm_path = DATA / "mm_extracted.jsonl"
    if mm_path.exists():
        mm = [json.loads(l) for l in mm_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        ym = [it["label"] for it in mm]
        sm, lm = run_engine(packages(mm))
        ref = {it["id"]: it for it in items}
        so, lo = run_engine(packages([ref[it["id"]] for it in mm]))  # same items, script text (oracle)
        res["multimodal"] = {
            "n": len(mm), "extraction": mm[0]["extraction"],
            "mean_ocr_cer": float(np.mean([it["ocr_cer"] for it in mm])),
            "extracted_alert": summarize("v2 on extracted (OCR+ASR*)", ym, [int(l in ALERT) for l in lm], sm, ci=True),
            "extracted_queue": summarize("v2 on extracted (OCR+ASR*)", ym, [int(l in QUEUE) for l in lm], sm, ci=True),
            "oracle_alert": prf(ym, [int(l in ALERT) for l in lo]),
            "oracle_queue": prf(ym, [int(l in QUEUE) for l in lo]),
        }
    (OUT / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    write_tables(res)
    plots(res, y, s2, s1)
    print((OUT / "tables.md").read_text(encoding="utf-8"))


def _f(x):
    return f"{x:.3f}"


def write_tables(res):
    L = ["# AIMW revision — SYNTHETIC benchmark results", "",
         f"> {res['note']}  n={res['n_items']} ({res['n_scam']} scam / {res['n_items'] - res['n_scam']} legitimate).",
         f"> Deployed thresholds: {res['deployed_thresholds']}. Operating points fixed in advance (no tuning on test data).", "",
         "## Table A — Systems and baselines", "",
         "| System | Precision | Recall | F1 | FPR | AUC | F1 95% CI |", "|---|---|---|---|---|---|---|"]
    for s in res["systems"]:
        ci = s.get("ci95", {}).get("f1", [float("nan")] * 2)
        L.append(f"| {s['system']} | {_f(s['precision'])} | {_f(s['recall'])} | {_f(s['f1'])} | {_f(s['fpr'])} | "
                 f"{_f(s['auc']) if 'auc' in s else '–'} | [{ci[0]:.3f}, {ci[1]:.3f}] |")
    L += ["", "## Table B — Rule ablations (v2, one rule removed at a time)", "",
          "| Removed | ALERT P | ALERT R | ALERT F1 | ALERT FPR | QUEUE P | QUEUE R | QUEUE F1 | QUEUE FPR |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k, v in sorted(res["ablations"].items()):
        a, q = v["alert"], v["queue"]
        name = "(none — full v2)" if k == "_full_v2" else k
        L.append(f"| {name} | {_f(a['precision'])} | {_f(a['recall'])} | {_f(a['f1'])} | {_f(a['fpr'])} | "
                 f"{_f(q['precision'])} | {_f(q['recall'])} | {_f(q['f1'])} | {_f(q['fpr'])} |")
    L += ["", "## Table C — Per-family flag rate (ALERT = HIGH+, QUEUE = MEDIUM+)", "",
          "| Family | v1 ALERT | v2 ALERT | v1 QUEUE | v2 QUEUE |", "|---|---|---|---|---|"]
    pf = res["per_family"]
    for fam in pf["v2_alert"]:
        L.append(f"| {fam} | {pf['v1_alert'][fam]['rate']:.2f} | {pf['v2_alert'][fam]['rate']:.2f} | "
                 f"{pf['v1_queue'][fam]['rate']:.2f} | {pf['v2_queue'][fam]['rate']:.2f} |")
    L += ["", "(For scam families the rate is recall; for legitimate families it is the false-positive rate.)", "",
          "## Table D — Modality", "", "| Input | ALERT P | ALERT R | ALERT F1 | QUEUE P | QUEUE R | QUEUE F1 |", "|---|---|---|---|---|---|---|"]
    for k, v in res["modality"].items():
        a, q = v["alert"], v["queue"]
        L.append(f"| {k} | {_f(a['precision'])} | {_f(a['recall'])} | {_f(a['f1'])} | {_f(q['precision'])} | {_f(q['recall'])} | {_f(q['f1'])} |")
    L += ["", "## Table E — Sensitivity: HIGH threshold sweep (single-source ceiling = HIGH − 0.01)", "",
          "| HIGH | Precision | Recall | F1 | FPR |", "|---|---|---|---|---|"]
    for m in res["sensitivity_high_threshold"]:
        mark = " ← deployed≈" if abs(m["high"] - res["deployed_thresholds"]["high"]) < 0.011 else ""
        L.append(f"| {m['high']:.2f}{mark} | {_f(m['precision'])} | {_f(m['recall'])} | {_f(m['f1'])} | {_f(m['fpr'])} |")
    L += ["", "## Table F — Sensitivity: weights ±20 % one-at-a-time (ALERT F1 / QUEUE F1)", "",
          "| Weight | ×0.8 ALERT F1 | ×1.2 ALERT F1 | ×0.8 QUEUE F1 | ×1.2 QUEUE F1 |", "|---|---|---|---|---|"]
    oat = defaultdict(dict)
    for r in res["sensitivity_weights_oat"]:
        oat[r["weight"]][r["factor"]] = r
    for w, d in oat.items():
        L.append(f"| {w} | {_f(d[0.8]['alert_f1'])} | {_f(d[1.2]['alert_f1'])} | {_f(d[0.8]['queue_f1'])} | {_f(d[1.2]['queue_f1'])} |")
    mc = res["sensitivity_weights_mc"]
    L += ["", f"Monte-Carlo joint ±20 % perturbation ({mc['draws']} draws): ALERT F1 mean {mc['alert_f1']['mean']:.3f} "
          f"[p5 {mc['alert_f1']['p5']:.3f}, p95 {mc['alert_f1']['p95']:.3f}]; QUEUE F1 mean {mc['queue_f1']['mean']:.3f} "
          f"[p5 {mc['queue_f1']['p5']:.3f}, p95 {mc['queue_f1']['p95']:.3f}].", "",
          f"Invariant check — single-modality packages labelled HIGH/CRITICAL: v1 = {res['invariant_single_source_high_violations_v1']}, "
          f"v2 = {res['invariant_single_source_high_violations']}.", ""]
    if "multimodal" in res:
        mm = res["multimodal"]
        ea, eq = mm["extracted_alert"], mm["extracted_queue"]
        L += ["## Table G — Rendered SYNTHETIC videos through real OCR", "",
              f"n={mm['n']} videos; extraction={mm['extraction']}; mean OCR character error rate={mm['mean_ocr_cer']:.3f}.", "",
              "| Input | ALERT P | ALERT R | ALERT F1 | QUEUE P | QUEUE R | QUEUE F1 |", "|---|---|---|---|---|---|---|",
              f"| Extracted (Tesseract OCR + ASR stand-in) | {_f(ea['precision'])} | {_f(ea['recall'])} | {_f(ea['f1'])} | {_f(eq['precision'])} | {_f(eq['recall'])} | {_f(eq['f1'])} |",
              f"| Oracle text (same items) | {_f(mm['oracle_alert']['precision'])} | {_f(mm['oracle_alert']['recall'])} | {_f(mm['oracle_alert']['f1'])} | {_f(mm['oracle_queue']['precision'])} | {_f(mm['oracle_queue']['recall'])} | {_f(mm['oracle_queue']['f1'])} |", ""]
    (OUT / "tables.md").write_text("\n".join(L), encoding="utf-8")


def plots(res, y, s2, s1):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sw = res["sensitivity_high_threshold"]
    h = [m["high"] for m in sw]
    plt.figure(figsize=(7, 4))
    for k in ("precision", "recall", "f1"):
        plt.plot(h, [m[k] for m in sw], label=k)
    plt.axvline(res["deployed_thresholds"]["high"], ls="--", c="k", label="deployed HIGH")
    plt.xlabel("HIGH threshold"); plt.ylabel("metric (ALERT operating point)")
    plt.title("Sensitivity to HIGH threshold — SYNTHETIC benchmark"); plt.legend(); plt.tight_layout()
    plt.savefig(OUT / "sensitivity_high_threshold.png", dpi=150); plt.close()

    y = np.asarray(y)
    plt.figure(figsize=(7, 4))
    bins = np.linspace(0, 1, 21)
    for lab, col, nm in ((0, "#16a34a", "legitimate"), (1, "#dc2626", "scam")):
        plt.hist(np.asarray(s2)[y == lab], bins=bins, alpha=0.6, color=col, label=f"{nm} (v2)")
    plt.axvline(res["deployed_thresholds"]["high"], ls="--", c="k", label="HIGH")
    plt.axvline(res["deployed_thresholds"]["medium"], ls=":", c="k", label="MEDIUM")
    plt.xlabel("final score"); plt.ylabel("items"); plt.title("Score distribution — SYNTHETIC benchmark (v2)")
    plt.legend(); plt.tight_layout(); plt.savefig(OUT / "score_distribution_v2.png", dpi=150); plt.close()

    names = [k for k in res["ablations"] if k != "_full_v2"]
    full = res["ablations"]["_full_v2"]
    plt.figure(figsize=(8, 4))
    x = np.arange(len(names))
    plt.bar(x - 0.2, [res["ablations"][k]["queue"]["f1"] - full["queue"]["f1"] for k in names], 0.4, label="ΔF1 QUEUE")
    plt.bar(x + 0.2, [res["ablations"][k]["queue"]["fpr"] - full["queue"]["fpr"] for k in names], 0.4, label="ΔFPR QUEUE")
    plt.xticks(x, names, rotation=30, ha="right"); plt.axhline(0, c="k", lw=0.8)
    plt.title("Ablation: change vs full v2 (SYNTHETIC)"); plt.legend(); plt.tight_layout()
    plt.savefig(OUT / "ablations.png", dpi=150); plt.close()


if __name__ == "__main__":
    main()

"""Honest re-analysis of the submitted real-video evaluation (fast mode).

The submitted numbers (Acc 81.8 %, P 79.2 %, R 95.0 %, F1 86.4 %, AUC 0.844 on
33 videos) came from evaluate.py, which
  (a) picked the decision threshold (21/100) that maximised accuracy ON THE
      SAME 33 videos it then reported on (optimistic bias), and
  (b) used folder labels assigned by the authors, partly with help of the same
      LLM judge (circular — R1/R2).

This script recomputes from the cached scores (../../eval_results.json):
  * metrics at PRE-REGISTERED thresholds 50 and 70 (the Local Agent's own
    MEDIUM / HIGH bands) — no tuning on test data;
  * leave-one-out cross-validated threshold selection (unbiased estimate of the
    "tuned threshold" procedure);
  * bootstrap 95 % CIs;
  * a *provisional* relabelling sensitivity check: titles that indicate
    scam-baiting / awareness content are, under the paper's own task
    definition (promotion vs. discussion), NEGATIVES. This is NOT a substitute
    for the independent annotation in REVISION/annotation/ — it only shows how
    much the conclusions depend on the labelling.
If REVISION/annotation/adjudicated_labels.csv exists (independent labels), it is
used as the primary ground truth instead.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

FRONTEND = Path(__file__).resolve().parents[2]
LOCAL_AGENT = FRONTEND.parent
SCORES = LOCAL_AGENT / "eval_results.json"
ADJ = LOCAL_AGENT / "REVISION" / "annotation" / "adjudicated_labels.csv"
AUTHOR = LOCAL_AGENT / "REVISION" / "annotation" / "author_labels.csv"
OUT = FRONTEND / "data" / "revision" / "results"

# Folder labels as used in the submission (20 scam / 13 safe). The last three
# keys were appended to the cache later; their folder is inferred from the
# reported 20/13 split and must be confirmed by the authors.
SAFE = {
    "5 min crafts be like - let's make easy TRIPLE Chocolate coffee 😎❤️🍫 - CHEFKOUDY.mp4",
    "food hacks - 5 minute crafts food.mp4",
    "I took off her staff, while she was sleeping, to make new Handcrafted leather cases for iPhone.mp4",
    "I Wish I Knew These Kitchen Hacks Sooner!.mp4",
    "IS JESUS GOD. #muslim #islam #religion #speakerscorner #dawah #christian.mp4",
    "Kevin De Bruyne- The Difference Maker #shorts #fifaworldcup #belgium.mp4",
    "Make an ice cream hole 🤫🍦.mp4",
    "Ranking What Sound Does a Dinosaur Make.mp4",
    "THE BEAUTY OF HUMANITY! ❤️‍🩹 - Headlights (Slowed).mkv",
    "What will you do in this situation. 😂😂😂 #funny.mp4",
    "Xi Jinping Honors Vladimir Putin 😳🔥 World Stunned.mp4",
    "بهترین نصیحت از زبان اولین تریلیونر جهان...!🤍👌#انگیزشی #موفقیت #پیشرفت #دیسیپلین #یوتیوب_فارسی.mp4",
    "Iran's goal against Belgium was disallowed after a VAR check for offsides. #worldcup2026 #iran.mp4",
}
UNCERTAIN_FOLDER = {
    "This Scammer Thinks I'm Cutting  Gift Cards #Shorts.mp4",
    "WhatsApp Video 2026-06-18 at 15.53.06.mp4",
    "Iran's goal against Belgium was disallowed after a VAR check for offsides. #worldcup2026 #iran.mp4",
}
# Titles that read as scam-baiting / awareness (discussing scams, not promoting).
BAITING = {
    "Calling a Scammer by his Real Name #shorts.mp4",
    "Cocky Scammer gets owned!     #scammers.mp4",
    "Scam Call 😳 (Animation Meme) Anim_ RedFlowerCrown #shorts.mp4",
    "Showing a Scammer his Own Face!.mp4",
    "This Scammer Thinks I'm Cutting  Gift Cards #Shorts.mp4",
}


def metrics(y, s, t):
    y, s = np.asarray(y), np.asarray(s)
    p = (s >= t).astype(int)
    tp = int(((p == 1) & (y == 1)).sum()); fp = int(((p == 1) & (y == 0)).sum())
    fn = int(((p == 0) & (y == 1)).sum()); tn = int(((p == 0) & (y == 0)).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
    return {"threshold": t, "accuracy": (tp + tn) / len(y), "precision": pr, "recall": rc,
            "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0, "fpr": fp / (fp + tn) if fp + tn else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def auc(y, s):
    y, s = np.asarray(y), np.asarray(s, float)
    pos, neg = s[y == 1], s[y == 0]
    return float(((pos[:, None] > neg).sum() + 0.5 * (pos[:, None] == neg).sum()) / (len(pos) * len(neg)))


def best_threshold(y, s):
    best, bt = -1, 50
    for t in range(5, 100):
        a = metrics(y, s, t)["accuracy"]
        if a > best:
            best, bt = a, t
    return bt


def loocv(y, s):
    y, s = np.asarray(y), np.asarray(s)
    pred = np.zeros(len(y), int); chosen = []
    for i in range(len(y)):
        m = np.ones(len(y), bool); m[i] = False
        t = best_threshold(y[m], s[m]); chosen.append(t)
        pred[i] = int(s[i] >= t)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
    return {"accuracy": (tp + tn) / len(y), "precision": pr, "recall": rc,
            "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0, "thresholds_chosen": sorted(set(chosen))}


def boot(y, s, t, n=2000, seed=0):
    rng = np.random.default_rng(seed); y, s = np.asarray(y), np.asarray(s)
    acc, f1, au = [], [], []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if len(set(y[i])) < 2:
            continue
        m = metrics(y[i], s[i], t); acc.append(m["accuracy"]); f1.append(m["f1"]); au.append(auc(y[i], s[i]))
    q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]  # noqa: E731
    return {"accuracy": q(acc), "f1": q(f1), "auc": q(au)}


def analyse(name, names, y, s):
    res = {"labels": name, "n": len(y), "n_pos": int(sum(y)), "auc": auc(y, s), "auc_ci95": boot(y, s, 50)["auc"]}
    res["submitted_procedure_threshold_tuned_on_test"] = metrics(y, s, best_threshold(y, s))
    for t in (50, 70):
        res[f"fixed_{t}"] = metrics(y, s, t); res[f"fixed_{t}_ci95"] = boot(y, s, t)
    res["loocv_threshold"] = loocv(y, s)
    return res


def main():
    scores = json.loads(SCORES.read_text(encoding="utf-8-sig"))
    names = list(scores)
    s = [float(scores[n]) for n in names]
    out = {"note": "Fast mode only (Whisper-tiny + mistral speech analyst + llama3 auditor; NO OCR, NO vision, "
                   "NO evidence briefs). Scores from the submitted run, not re-generated.",
           "uncertain_folder_labels": sorted(UNCERTAIN_FOLDER)}
    y_folder = [0 if n in SAFE else 1 for n in names]
    out["folder_labels"] = analyse("folder (submitted)", names, y_folder, s)
    if AUTHOR.exists():
        al = {r["video"]: r["final_label"] for r in csv.DictReader(AUTHOR.open(encoding="utf-8"))}
        y_auth = [int(al[n] == "scam") for n in names]
        out["author_final_labels"] = analyse(
            "author's final labels (manual, before running the system; scam-baiting = safe)", names, y_auth, s)
    else:
        y_relab = [0 if (n in SAFE or n in BAITING) else 1 for n in names]
        out["provisional_relabel_baiting_as_negative"] = analyse("provisional: scam-baiting titles → negative", names, y_relab, s)
    out["score_value_counts"] = {str(k): int(v) for k, v in zip(*np.unique(s, return_counts=True))}
    if ADJ.exists():
        lab = {r["video"]: r for r in csv.DictReader(ADJ.open(encoding="utf-8"))}
        keep = [n for n in names if n in lab and lab[n]["final_label"] in ("promotion", "not_promotion")]
        out["independent_labels"] = analyse("independent adjudicated", keep,
                                            [int(lab[n]["final_label"] == "promotion") for n in keep],
                                            [float(scores[n]) for n in keep])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "real_corpus_reanalysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    def row(tag, m):
        return f"| {tag} | {m['accuracy']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} |"
    L = ["# Real-video corpus (n=33) — re-analysis of the submitted fast-mode scores", "", f"> {out['note']}", ""]
    for key in ("author_final_labels", "folder_labels", "provisional_relabel_baiting_as_negative", "independent_labels"):
        if key not in out:
            continue
        r = out[key]
        L += [f"## Labels: {r['labels']} (n={r['n']}, positives={r['n_pos']})", "",
              f"AUC = {r['auc']:.3f} (95% CI {r['auc_ci95'][0]:.3f}–{r['auc_ci95'][1]:.3f})", "",
              "| Procedure | Accuracy | Precision | Recall | F1 |", "|---|---|---|---|---|",
              row(f"Submitted: threshold tuned on test ({r['submitted_procedure_threshold_tuned_on_test']['threshold']})",
                  r["submitted_procedure_threshold_tuned_on_test"]),
              row("Pre-registered threshold 50", r["fixed_50"]),
              row("Pre-registered threshold 70", r["fixed_70"]),
              row(f"LOOCV-selected threshold (chosen: {r['loocv_threshold']['thresholds_chosen']})", r["loocv_threshold"]),
              "", f"F1 95% CI at threshold 50: {r['fixed_50_ci95']['f1'][0]:.3f}–{r['fixed_50_ci95']['f1'][1]:.3f}", ""]
    (OUT / "real_corpus_reanalysis.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

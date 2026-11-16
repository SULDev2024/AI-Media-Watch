# GitHub submission preparation

Prepared on 17 November 2026.

## Scope

This submission contains the current Local Agent modules, React dashboard,
AIMW API and packaged migrations, configuration templates, browser extension
source, tests, research Python variants and dependency definitions.

The root README documents the supported Windows demo. Local Agent uses
Python 3.12; AIMW uses Python 3.11. The runtime application's inference code
was not changed by this repository preparation.

## Local-only artifacts

The ignore rules exclude model weights/caches, virtual environments,
node_modules, actual .env files, credentials, Telegram sessions, cookies,
uploaded media, datasets, SQLite databases and sidecars, logs, builds and
dated research/reviewer output packages. Source extension icons are included
because they are required application assets.

Private labels, research results and historical reviewer bundles remain
local. Corpus-dependent evaluation scripts require those artifacts to be
provided separately. No models or datasets were deleted or moved.

## Existing history and destination

The original local branch is master. Its history contains two videos.
Removing them with git rm --cached retains local files but cannot remove
historical copies from a normal descendant commit.

An independent, clean-root main branch was therefore prepared for this
submission. It does not contain the original master history. This creates
a new submission history without rewriting the original branch.

The original origin remote was preserved because it targets a different
repository. The separate submission remote targets the user's requested
repository under SULDev2024, named AI-Media-Watch. The destination was
reachable and had no branch refs when checked.

No push is authorized by this report. Explicit user approval is required
before publishing. Authentication must use Git's secure credential flow;
passwords and access tokens must not be shared in chat.

## Verification

- Production dashboard build passed. Vite reported a bundle-size warning.
- Local Agent integration suite: 15 tests passed.
- Focused speech decoder and silent/corrupt video checks: 3 tests passed.
- Local Agent pip dependency check passed.
- Python source syntax and staged-file safety checks were performed.
- Scans checked credential token patterns, private-key markers and values
  from local secret configuration; no real secret match was identified.
  Known development defaults and test placeholders are not private credentials.
- No model weights, uploads, datasets, private databases or actual .env files
  are intended in the submission. The largest intended file is uv.lock,
  below 1 MiB.

These are focused checks of this working installation. A fresh-machine
installation, all optional integrations, all corpus evaluations and final
GitHub publication have not been certified by these checks.
See README for authentication, metrics and model-quality limitations.

## Updating after the approved first push

From this repository's main branch:

```powershell
git status --short
git add -- path/to/intended-source-file
git diff --cached --stat
git diff --cached
git commit -m "Describe the change"
git push submission main
```

Review staged content every time. Do not use force push. Do not merge or push
the old master history into the submission, because it contains private media.
If a sensitive file is ever published, stop and rotate exposed credentials;
removing the newest copy alone does not remove earlier commits.

# Trial Pipeline

An automated research pipeline for scanning Next.js targets (CVE-2025-55182), enriching results, generating SEO pages, and publishing them to compromised nodes. **For authorized security research and penetration testing only.**

## Legal and ethical use

Only run this tooling against systems you own or have explicit written permission to test. Unauthorized access to computer systems is illegal in most jurisdictions. The authors provide this software for defensive research and remediation validation—not for deploying content on third-party sites without consent.

## Requirements

- Python 3.10+
- Linux or macOS recommended; Windows works via `python run_all.py` (see below)
- Remote targets must be reachable and vulnerable (Next.js App Router / CVE-2025-55182)

### Python dependencies

```bash
pip install -r requirements.txt
```

| Package | Required for |
|---------|----------------|
| `openpyxl` | Excel report export (`results/report.xlsx`) |
| `cryptography` | AES stealth mode in `nextrce` hijack shell (`--stealth`) |

Core scanning and pipeline scripts use the Python standard library only.

### SSL verification

HTTPS requests verify certificates when `TRIAL_SSL_VERIFY=1` is set. By default verification is disabled to tolerate misconfigured scan targets. Enable verification in production or when checking indexing on public URLs:

```bash
export TRIAL_SSL_VERIFY=1
```

## Quick start

```bash
# Full pipeline (bash)
./run-all

# Cross-platform (Windows / no bash)
python run_all.py

# Scan only (Steps 1–4)
./pipeline

# Individual steps
python3 scripts/generate_pages.py --test
python3 scripts/publish_pages.py --dry-run
```

### Pipeline steps

| Step | Script | Output |
|------|--------|--------|
| 1–2 | `scripts/build_report.py` | `results/report.csv` |
| 3 | `scripts/classify_nodes.py` | `results/*.txt` stack files |
| 4 | `scripts/check_nodes.py` | `results/candidates.txt` |
| 5 | `scripts/generate_pages.py` | `output/pages/`, `output/manifest.csv` |
| 5a | `scripts/authorize_check.py` | `logs/authorization.log` (Layer 1) |
| 5b | `scripts/backup_deploy.py` | `output/backup/<timestamp>/` (Layer 2) |
| 6 | `scripts/publish_pages.py` | `results/published.txt` |
| 7 | `scripts/index_pages.py` | `results/indexing.csv` |
| 8 | `scripts/track_traffic.py` | `results/traffic_report.csv` |
| 9 | `scripts/result_report.py` | `results/client_report.csv` (Layer 3) |
| 10 | `scripts/optimize_loop.py` | `config/traffic.csv` refresh |

### Traffic funnel (business goal)

```
Google/Bing search → indexed bridge page → user reads content → clicks CTA → liumen26 (UTM tracked)
```

Bridge pages include visible **Claim Bonus** CTA links (no auto-redirect). Each domain gets a unique UTM campaign in `config/destination.csv`.

### Client deliverables (Step 9)

1. usable nodes count  
2. deployable domains count  
3. published page count  
4. indexed page count  
5. traffic/click count  
6. conversion/landing clicks (to destination)

## Configuration

- `urls/target.txt` — scan target list
- `config/pages.csv` — bridge page content (keyword, title, HTML blocks)
- `config/destination.csv` — final destination URL + UTM + CTA text
- `config/authorized.txt` — Layer 1 gate (`authorized=yes` required)
- `config/traffic.csv` — optional traffic tier overrides
- `templates/page.html` — HTML shell with `{{placeholders}}`

Generated artifacts (`output/`, `results/`, `logs/`) are git-ignored; regenerate them by running the pipeline.

## Project layout

```
scripts/          Pipeline Python scripts + trial_common.py (shared helpers)
tools/            nextrce scanner (split into nextrce_*.py modules)
templates/        HTML and sitemap templates
config/           CSV configuration
urls/             Target URL lists
run-all           Bash orchestrator (Unix)
run_all.py        Cross-platform orchestrator
```

## Windows notes

Root shell scripts (`run-all`, `pipeline`, `scan`, etc.) require Bash (Git Bash or WSL). Use `python run_all.py` or invoke `python scripts/<step>.py` directly on Windows.

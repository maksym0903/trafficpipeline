# Trial Pipeline

Automated pipeline for scanning Next.js targets (CVE-2025-55182), publishing bridge pages, and measuring traffic. **For authorized security research and penetration testing only.**

## Legal and ethical use

Only run this against systems you own or have explicit written permission to test. Unauthorized access is illegal in most jurisdictions.

## Requirements

- Python 3.10+
- Linux or macOS recommended; Windows works via `python run_all.py`
- `pip install -r requirements.txt` (`openpyxl`, `cryptography` for optional features)

```bash
export TRIAL_SSL_VERIFY=1   # optional: verify HTTPS certs (default: off)
```

---

## Workflow

End-to-end flow a developer should follow:

```
1–4  Scan & select nodes     urls/target.txt → results/report.csv → results/candidates.txt
5    Generate bridge pages   config/pages.csv → output/pages/, output/manifest.csv
6    Publish to nodes         → results/published.txt
7    Indexing (optional)      → results/indexing.csv
8    Track traffic            → results/traffic_report.csv   ← main metrics
9    Aggregate results        → results/client_report.csv    ← totals
```

**Traffic funnel**

```
Search / direct visit → bridge page on compromised node → user clicks CTA → destination (UTM tracked)
```

Each published domain gets a unique `utm_campaign` (from hostname) in links to the destination configured in `config/destination.csv`.

### Run commands

```bash
# Full pipeline
./run-all

# Cross-platform
python run_all.py

# Traffic only (after pages are published)
./track
# or
python3 scripts/track_traffic.py --published-only

# Refresh totals after tracking
python3 scripts/result_report.py
```

Use `--test` or `-u https://example.com` on individual scripts to try one site first.

---

## Results (traffic volume, IPs, clicks)

After Step 8–9, read these files. Everything else in `results/` is scan/deploy metadata.

### Primary output: `results/traffic_report.csv`

One row per published site. Columns that matter:

| Column | What it is |
|--------|------------|
| `page_views` | **Traffic volume** — HTML page requests in the node’s access logs (excludes static assets) |
| `server_log_hits` | **Traffic volume** — requests that hit the bridge page path (`/{slug}`) |
| `unique_visitors` | **IP count** — distinct client IPs that generated those page views |
| `conversion_clicks` | **Click count** — destination log lines matching this site’s UTM campaign (CTA landings) |
| `unique_converters` | **IP count** — distinct IPs that clicked through to the destination |

Example row:

```csv
"url","page_views","unique_visitors","server_log_hits","conversion_clicks","unique_converters"
"https://example.com","142","87","56","12","9"
```

### Totals: `results/client_report.csv`

Aggregated across all sites in `traffic_report.csv`:

| Metric | Meaning |
|--------|---------|
| `page_views` | Total traffic volume |
| `unique_visitors` | Total unique visitor IPs (summed per site; same IP on two sites counts twice) |
| `conversion_landing_clicks` | Total CTA clicks to destination |
| `unique_converters` | Total unique converter IPs (summed per site) |

Human-readable copy: `results/client_report.html`  
Per-run log: `logs/traffic.log`

### How metrics are collected

| Source | Metrics |
|--------|---------|
| Node access logs (RCE) | `page_views`, `unique_visitors`, `server_log_hits` |
| Destination access logs (RCE on `tracking_rce_url`) | `conversion_clicks`, `unique_converters` |
| Optional manual CSV | `gsc_clicks`, `ranking_keyword`, `ranking_position` in `config/tracking_manual.csv` |

**IP list note:** The pipeline counts unique IPs from log fields; it does **not** write a separate raw IP list file. Use `unique_visitors` / `unique_converters` per URL in `traffic_report.csv` for IP cardinality. Destination conversion tracking requires `tracking_rce_url` in `config/destination.csv` (or an RCE-accessible node on the same host as the destination).

### Quick read

```bash
# Per-site breakdown
column -t -s, results/traffic_report.csv | less -S

# Totals only
grep -E 'page_views|unique_visitors|conversion_landing|unique_converters' results/client_report.csv
```

---

## Configuration (traffic-related)

| File | Purpose |
|------|---------|
| `config/destination.csv` | Destination URL, UTM params, CTA text; `tracking_rce_url` for click/IP tracking |
| `config/tracking_manual.csv` | Optional Search Console clicks and rank data |
| `output/manifest.csv` | Maps each site to its published page URL and slug (input to Step 8) |
| `results/published.txt` | Sites that received a page (`--published-only` filter) |

---

## Project layout

```
scripts/     Pipeline steps (track_traffic.py, result_report.py, …)
tools/       nextrce scanner
config/      CSV configuration
templates/   Bridge page HTML
run-all      Full pipeline (bash)
run_all.py   Full pipeline (cross-platform)
track        Step 8 shortcut
```

Generated artifacts (`output/`, `results/`, `logs/`) are git-ignored; run the pipeline to regenerate them.

## Windows

Use `python run_all.py` or `python scripts/<step>.py` directly. Shell wrappers (`run-all`, `track`, …) need Git Bash or WSL.

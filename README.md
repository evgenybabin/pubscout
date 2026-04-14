# PubScout

CLI-driven publication scanning agent — fetches, filters, scores, and reports new research papers from arXiv, Semantic Scholar, RSS feeds, and the web.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What It Does

PubScout automates the tedious work of staying current with research. Define your domains of interest using boolean queries, point it at publication sources, and let it:

1. **Fetch** papers from multiple sources (arXiv API, Semantic Scholar API, RSS/Atom feeds, web pages)
2. **Deduplicate** results across sources using fuzzy title matching + DOI/arXiv ID
3. **Score** relevance using an LLM (GPT-4o-mini by default) against your domain queries
4. **Report** top results as an HTML digest — delivered by email or saved to file
5. **Learn** from your feedback to improve future scoring

---

## Quick Start

### Install

```bash
# Clone and install with uv (recommended)
git clone https://github.com/evgenybabin/pubscout.git
cd pubscout
uv sync

# Or with pip
pip install -e .
```

### Initialize

```bash
# Interactive setup — walks you through domains, sources, email, and LLM config
pubscout init

# Or non-interactive with defaults (6 sources, 6 research domains)
pubscout init --non-interactive
```

### Run Your First Scan

```bash
# First scan — show all matching papers (skip database dedup)
pubscout scan --dry-run --first-run

# Subsequent scans — only new papers since last run
pubscout scan --dry-run

# Full scan with email delivery
pubscout scan

# Skip email, just save report
pubscout scan --no-email

# Scan last 14 days instead of default 7
pubscout scan --days 14
```

---

## Configuration

PubScout stores its profile at `~/.pubscout/profile.yaml`. The interactive `init` wizard creates this file, but you can also manage it entirely via CLI commands.

### Profile Structure

```yaml
version: 2
scan_range_days: 7       # Only papers from the last N days (1–365)
domains:
  - label: "LLM Disaggregated Inference"
    query: '"large language model" AND "disaggregated inference"'
    enabled: true
sources:
  - label: arXiv
    type: api
    url: "https://export.arxiv.org/api/query"
    adapter: arxiv
    enabled: true
    config:
      categories: [cs.LG, cs.AI, cs.DC, cs.PF, cs.AR, cs.CL]
      lookback_days: 1
email:
  transport: smtp          # "smtp" or "file"
  from_addr: you@example.com
  to_addr: you@example.com
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_use_tls: true
  smtp_username: you@example.com
  smtp_password_env: PUBSCOUT_SMTP_PASS   # env var name, not the password
llm:
  provider: openai         # "openai" or "azure"
  model: gpt-4o-mini
  api_key: null            # uses OPENAI_API_KEY env var if null
  # Azure OpenAI fields (only when provider: azure):
  # endpoint: https://YOUR-RESOURCE.openai.azure.com
  # api_version: "2024-06-01"
  # deployment_name: your-deployment-name
scoring:
  threshold: 5.0           # 1.0–10.0, papers below this are filtered out
  include_keywords: []     # boost score for papers containing these
  exclude_keywords: []     # penalize papers containing these
```

### LLM Providers

PubScout supports two LLM providers for relevance scoring:

**OpenAI (default):**
```yaml
llm:
  provider: openai
  model: gpt-4o-mini
```
Set `OPENAI_API_KEY` environment variable or `api_key` in profile.

**Azure OpenAI:**
```yaml
llm:
  provider: azure
  model: gpt-4o-mini
  deployment_name: my-gpt4o-mini    # Your Azure deployment name
  endpoint: https://MY-RESOURCE.openai.azure.com
  api_version: "2024-06-01"
```
Set `AZURE_OPENAI_API_KEY` environment variable or `api_key` in profile. The `deployment_name` is used as the model parameter in API calls. Get the endpoint and key from Azure Portal → your OpenAI resource → Keys and Endpoint.

### Environment Variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key for LLM scoring (provider: openai) |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key (provider: azure) |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint (provider: azure) |
| `S2_API_KEY` | Semantic Scholar API key (optional, increases rate limits) |
| `PUBSCOUT_SMTP_PASS` | SMTP password (env var name is configurable in profile) |

---

## CLI Reference

### `pubscout init` — Setup Wizard

```bash
pubscout init                    # Interactive setup
pubscout init --non-interactive  # Use defaults
pubscout init --sources-file urls.txt  # Import source URLs from file
```

### `pubscout scan` — Run a Scan

```bash
pubscout scan                       # Full scan + email
pubscout scan --dry-run             # Report to file only
pubscout scan --no-email            # Scan + save, skip email
pubscout scan --first-run           # Show all papers (skip database dedup)
pubscout scan --days 14             # Override scan range (default: 7 days from profile)
pubscout scan --timeout 60          # Custom HTTP timeout per source
pubscout scan -p custom-profile.yaml  # Use a different profile
```

Use `--first-run` on your initial scan to see all matching papers. Subsequent scans automatically show only new publications since the last run.

### `pubscout sources` — Manage Sources

```bash
pubscout sources                      # List all sources
pubscout sources add URL              # Add a URL (auto-detects type)
pubscout sources add URL --name "My Feed" --type rss
pubscout sources remove "My Feed"     # Remove by label
pubscout sources enable "My Feed"     # Enable a disabled source
pubscout sources disable "My Feed"    # Disable without removing
pubscout sources test URL             # Probe a URL — shows detected type, reachability
pubscout sources export               # Print all source URLs (one per line)
pubscout sources import urls.txt      # Bulk import from file
pubscout sources catalog              # List built-in source catalog
```

**Supported source types:**

| Type | Adapter | Description |
|---|---|---|
| `api` | `arxiv` | arXiv API with category filtering and lookback window |
| `api` | `semantic_scholar` | Semantic Scholar API with rate limiting and API key support |
| `rss` | `rss` | Any RSS/Atom feed (auto-detected via feedparser) |
| `web` | `web` | Generic web scraper — extracts papers from JSON-LD, `<article>` elements, or heading+link patterns |

### `pubscout domains` — Manage Research Domains

```bash
pubscout domains                      # List all domains
pubscout domains add "My Topic" '"keyword1" AND "keyword2"'
pubscout domains remove "My Topic"
pubscout domains enable "My Topic"
pubscout domains disable "My Topic"
pubscout domains catalog              # List built-in domain catalog
```

Domains use **boolean query syntax** for matching:
```
"large language model" AND (inference OR serving) AND "KV cache"
```

### `pubscout config` — Tuning

```bash
pubscout config show                  # Display current scoring/scan config
pubscout config threshold 7.0         # Set minimum relevance score (1.0–10.0)
pubscout config scan-range 14         # Set scan time range in days (1–365, default: 7)
pubscout config model gpt-4o          # Change LLM model
pubscout config include-add "transformer"   # Boost papers with this keyword
pubscout config include-remove "transformer"
pubscout config exclude-add "survey"        # Penalize papers with this keyword
pubscout config exclude-remove "survey"
```

### `pubscout db` — Database Management

```bash
pubscout db reset                     # Clear publications + scan history (preserves feedback)
pubscout db reset --yes               # Skip confirmation prompt
```

Use `db reset` when you want the next scan to treat every paper as new, without losing your feedback history.

### `pubscout email` — Email Delivery

```bash
pubscout email test                   # Send a test email to verify SMTP config
```

Email requires SMTP configuration in the profile. Set `transport: smtp` and configure host, port, and credentials. The password is read from an environment variable (not stored in the profile).

### `pubscout feedback` — Relevance Feedback

```bash
pubscout feedback list                       # Show recent feedback entries
pubscout feedback record PUB_ID up           # Positive feedback
pubscout feedback record PUB_ID down         # Negative feedback
pubscout feedback import feedback.json       # Import feedback from HTML report export
```

The HTML report includes inline 👍/👎 buttons per paper. Clicks are stored in your browser's `localStorage` and can be exported as a JSON file via the floating "Save feedback.json" bar. Import the file with `pubscout feedback import` to persist ratings in SQLite for future scoring improvement. No server required — everything works offline.

### `pubscout history` — Scan History

```bash
pubscout history                      # Show recent scan runs
```

### `pubscout stats` — Dashboard

```bash
pubscout stats                        # Show aggregate statistics
pubscout stats --since 2024-01-01     # Filter by date
```

Displays: total publications, reported count, scan count, feedback breakdown, per-domain stats, per-source stats.

### `pubscout schedule` — Automation

```bash
pubscout schedule show                # Show recommended cron/Task Scheduler command
```

Prints a platform-appropriate command to schedule daily scans:
- **Linux/macOS:** crontab entry
- **Windows:** `schtasks` command

---

## Architecture

```
src/pubscout/
├── adapters/             # Source-specific fetchers
│   ├── arxiv.py          #   arXiv API adapter
│   ├── semantic_scholar.py  # Semantic Scholar API adapter
│   ├── rss_adapter.py    #   RSS/Atom feed adapter
│   └── web_adapter.py    #   Generic web scraper
├── cli/
│   └── main.py           # Click CLI with 11 command groups
├── core/
│   ├── dedup.py          # Fuzzy deduplication (DOI → arXiv ID → title similarity)
│   ├── email.py          # SMTP email sender (STARTTLS/SSL)
│   ├── models.py         # Pydantic models (UserProfile, Source, Domain, etc.)
│   ├── pipeline.py       # Orchestrator: fetch → dedup → date filter → score → report → email
│   ├── profile.py        # Profile YAML I/O + v1→v2 migration
│   ├── query.py          # Boolean query parser
│   ├── report.py         # Jinja2 HTML report generator
│   ├── scorer.py         # LLM-based relevance scoring (OpenAI + Azure OpenAI)
│   └── source_detect.py  # URL auto-detection (RSS vs web vs API)
└── storage/
    └── database.py       # SQLite: publications, scan runs, feedback, stats
```

**Data flow:**

```
Sources ──→ Adapters ──→ Dedup ──→ Scorer ──→ Reporter ──→ Email
Sources → Adapters → Date Filter (N days) → Dedup → Scorer → Reporter → Email
                                            │                    │
                                         SQLite ← Feedback (localStorage → JSON → import)

---

## Default Sources

PubScout ships with 6 pre-configured sources:

| Source | Type | Adapter | Description |
|---|---|---|---|
| arXiv | API | `arxiv` | arXiv API with category filtering (cs.LG, cs.AI, cs.DC, cs.PF, cs.AR, cs.CL) |
| Semantic Scholar | API | `semantic_scholar` | Semantic Scholar API with rate limiting |
| ACL Anthology | RSS | `rss` | ACL Anthology publications feed |
| PapersWithCode | Web | `web` | Trending papers from Papers With Code |
| OpenReview | Web | `web` | Conference submissions (limited by robots.txt) |
| Microsoft Research Blog | Web | `web` | Microsoft Research blog posts |

These can be customized via `pubscout sources add/remove` or by editing `profile.yaml`.

---

## Default Research Domains

PubScout ships with 6 pre-configured domains focused on LLM inference systems:

| Domain | Query Focus |
|---|---|
| LLM Disaggregated Inference | Prefill/decode separation, KV cache management |
| Inference Performance Modeling | Analytical models, roofline analysis |
| Inference Cost Efficiency | TCO, performance-per-dollar, cost optimization |
| Low-Precision & Quantization | FP8, BF16, INT8, quantization techniques |
| Efficient Compute Kernels | Attention kernels, GEMM, FlashAttention |
| RL-Based Code & Kernel Generation | Reinforcement learning for code generation |

These can be fully customized via `pubscout domains add/remove` or by editing `profile.yaml`.

---

## Database

PubScout uses SQLite at `~/.pubscout/pubscout.db` to persist:

- **Publications** — all fetched papers with scores, domains, and dedup IDs
- **Scan runs** — timestamps, item counts, errors, duration
- **Feedback** — user signals (positive/negative) per publication

The database is created automatically on first scan. No external database server needed.

Use `pubscout db reset` to clear publications and scan history while preserving feedback. This is useful when you want to re-scan without dedup filtering, or to start fresh after changing domains or sources.

---

## Development

```bash
# Setup
git clone https://github.com/evgenybabin/pubscout.git
cd pubscout
uv sync

# Run tests (223 tests)
uv run pytest tests/ -q

# Run with verbose output
uv run pytest tests/ -v --tb=short

# Run a specific test file
uv run pytest tests/unit/test_cli.py -v
```

### Test Coverage

| Module | Tests |
|---|---|
| CLI (all commands) | ~40 |
| Pipeline orchestrator | ~15 |
| arXiv adapter | ~15 |
| Semantic Scholar adapter | ~10 |
| RSS adapter | ~10 |
| Web adapter | ~8 |
| Database + stats | ~25 |
| Dedup, scorer, models, profile | ~50 |
| Email, source detection, feedback, scan range | ~31 |
| **Total** | **223** |

---

## License

MIT

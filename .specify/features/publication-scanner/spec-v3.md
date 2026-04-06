# Feature Specification: Publication Scanner Agent

**Feature Branch**: `001-publication-scanner`  
**Created**: 2026-03-26  
**Updated**: 2026-04-06  
**Status**: Draft — v3 (adds scan time range, local feedback, JSON import)  
**Spec Version**: 3.0  
**Previous Versions**: `spec-v1.md` (archived), `spec-v2.md` (archived)  
**Input**: Agentic system that scans web resources for new publications in user-defined domains within a configurable time range, filters by relevance, generates email digests with inline feedback, and refines via user feedback.

---

## Changelog (v2 → v3)

| Section | Change |
|---|---|
| Scan Time Range | NEW — `scan_range_days` parameter (default: 7) filters publications by age |
| Pipeline | Added centralized date filter step between fetch and dedup |
| Feedback System | REDESIGNED — Replaced HTTP server with self-contained local JS in HTML reports |
| Feedback CLI | Replaced `feedback serve` with `feedback import <file>` for JSON import |
| Relevance Tuning CLI | Added `config scan-range <days>` command |
| Scan CLI | Added `--days` flag for ad-hoc scan range override |
| Profile | Added `scan_range_days` field to UserProfile (1–365, default 7) |

### Changelog (v1 → v2)

| Section | Change |
|---|---|
| Source Configuration | Added S2 (Semantic Scholar), S3 (RSS/Atom), S4 (Generic Web Scraper) |
| Email Delivery | NEW — SMTP and Microsoft Graph API delivery specification |
| Feedback System | NEW — HTTP server and CLI feedback command specification |
| Interactive Init | NEW — Guided setup wizard specification |
| Source Management CLI | NEW — Full CRUD commands for sources |
| Domain Management CLI | NEW — CRUD commands for domains |
| Relevance Tuning CLI | NEW — CLI commands for scoring config |
| Statistics CLI | NEW — `stats` command specification |
| Profile Migration | NEW — Schema versioning and auto-migration |
| Scheduler Integration | NEW — OS scheduler setup documentation |
| Open Questions | 5 questions resolved with design decisions |
| Implementation Notes | NEW — v0.1 status annotations on all requirements |

---

## System Overview

**PubScout** is a CLI-driven agentic pipeline that:
1. Accepts user-defined domains, keywords, and (optionally) source URLs
2. Scans configured sources for publications within a configurable time range (default: last 7 days)
3. Deduplicates against previously seen publications
4. Scores each new publication for relevance using keyword matching + LLM analysis
5. Generates an HTML email digest with inline 👍/👎 feedback buttons (no server required)
6. Sends the digest via SMTP or Microsoft Graph API (or saves to file in dry-run mode)
7. Collects feedback (via JSON export/import) to refine future relevance scoring

The system runs as a scheduled CLI invocation — it is **not** a long-running service.

---

## Domain Configuration — Initial Interest Areas

The user profile supports structured boolean search queries that define areas of interest. Each query combines a **base topic** with **specialization facets** using AND/OR operators. The system uses these queries for two purposes: (a) constructing API search queries for sources that support structured search (arXiv, Semantic Scholar), and (b) feeding the LLM scorer with domain context for relevance assessment.

### Default Domain Queries (v1 Profile)

The following queries represent the initial areas of interest. Each is a standalone domain that the system evaluates independently — a publication matching **any one** domain is considered a candidate.

| # | Domain Label | Structured Query |
|---|---|---|
| D1 | **LLM Disaggregated Inference** | `("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("disaggregated inference" OR "prefill" OR "decode" OR "KV cache")` |
| D2 | **Inference Performance Modeling** | `("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("performance modeling" OR "analytical model" OR roofline)` |
| D3 | **Inference Cost Efficiency** | `("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("performance per dollar" OR "cost efficiency" OR TCO OR "efficiency")` |
| D4 | **Low-Precision & Quantization** | `("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("low precision" OR FP8 OR BF16 OR INT8 OR quantization)` |
| D5 | **Efficient Compute Kernels** | `("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("efficient kernels" OR "attention kernels" OR GEMM)` |
| D6 | **RL-Based Code & Kernel Generation** | `("large language model" OR LLM OR transformer) AND ("reinforcement learning" OR "RL-based" OR "learned code generation")` |

### Query Semantics

- **OR** within parentheses: synonyms / alternative phrasings — any match satisfies the clause.
- **AND** between clauses: all clauses must be present (in title, abstract, or keywords) for a positive match.
- The **base topic** (`"large language model" OR LLM OR transformer`) AND (`inference OR serving`) is shared across D1–D5, ensuring all results are grounded in LLM inference. D6 broadens to RL-based generation without requiring the inference facet.
- Queries are stored in `profile.yaml` under `domains[].query` and are **user-editable** — users can add, modify, or remove domains at any time via `pubscout init`, `pubscout domains`, or direct YAML editing.
- The scoring pipeline uses domain queries in two ways:
  1. **Keyword pre-filter**: Boolean evaluation against title + abstract text (fast, no LLM cost).
  2. **LLM context**: Matched domain labels and queries are passed to the LLM scorer as "the user is interested in: {domain_label}" to guide relevance assessment.

### Profile YAML Example

```yaml
scan_range_days: 7                  # Only include papers from the last N days (1–365)
domains:
  - label: "LLM Disaggregated Inference"
    query: '("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("disaggregated inference" OR "prefill" OR "decode" OR "KV cache")'
    enabled: true
  - label: "Inference Performance Modeling"
    query: '("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("performance modeling" OR "analytical model" OR roofline)'
    enabled: true
  - label: "Inference Cost Efficiency"
    query: '("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("performance per dollar" OR "cost efficiency" OR TCO OR "efficiency")'
    enabled: true
  - label: "Low-Precision & Quantization"
    query: '("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("low precision" OR FP8 OR BF16 OR INT8 OR quantization)'
    enabled: true
  - label: "Efficient Compute Kernels"
    query: '("large language model" OR LLM OR transformer) AND (inference OR serving) AND ("efficient kernels" OR "attention kernels" OR GEMM)'
    enabled: true
  - label: "RL-Based Code & Kernel Generation"
    query: '("large language model" OR LLM OR transformer) AND ("reinforcement learning" OR "RL-based" OR "learned code generation")'
    enabled: true
```

---

## Scan Time Range ✅ Implemented v0.2

The scan time range controls how far back PubScout looks for publications. Publications older than the cutoff are filtered out **after** fetching but **before** deduplication and scoring. This reduces noise and focuses results on recent work.

### Configuration

| Property | Value |
|---|---|
| **Profile field** | `scan_range_days` |
| **Type** | Integer (1–365) |
| **Default** | `7` (one week) |
| **CLI persistent** | `pubscout config scan-range <days>` |
| **CLI ad-hoc override** | `pubscout scan --days <days>` |

### Pipeline Behavior

1. After Step 1 (Fetch) completes, compute `cutoff = now_utc - timedelta(days=scan_range_days)`.
2. Remove all publications where `publication_date < cutoff`.
3. Publications with `publication_date = None` are **kept** (not filtered) — some sources or extraction methods may not provide dates.
4. Log the count of filtered-out publications for visibility.
5. Proceed to Step 2 (Dedup) with the filtered set.

The `--days` CLI flag overrides the profile value for a single scan invocation. If neither is specified, the profile default (7) is used.

### Profile YAML — Scan Range Example

```yaml
scan_range_days: 14    # Include papers from the last two weeks
```

---

## Source Configuration — Default Sources

The system ships with pre-configured default sources that map well to the domain queries above. Users can enable/disable defaults and add arbitrary URLs during `init` or at any time via `pubscout sources`.

### S1: arXiv (Default — Enabled) ✅ Implemented v0.1

| Property | Value |
|---|---|
| **Label** | arXiv |
| **Type** | API |
| **Base URL** | `http://export.arxiv.org/api/query` |
| **Adapter** | `ArxivAdapter` — uses the arXiv Search API (Atom XML responses) |
| **Python client** | `arxiv` PyPI package (handles pagination, rate limiting, result parsing) |
| **Auth** | None required (public API) |
| **Rate limits** | 3-second delay between requests (courtesy, not enforced). Max 2,000 results per page, 30,000 per query. |
| **Query mapping** | Domain boolean queries are translated to arXiv query syntax: `ti:` (title), `abs:` (abstract), `cat:` (category). OR/AND operators supported natively. |
| **Sort** | `sortBy=submittedDate&sortOrder=descending` for daily scans (newest first) |
| **Pagination** | `start` + `max_results` parameters; fetch in pages of 100 |
| **Dedup key** | arXiv ID (e.g., `2401.12345`) — globally unique, preferred over DOI for arXiv papers |

**Relevant arXiv categories** (pre-configured as category filters to reduce noise):

| Category | Name | Why relevant |
|---|---|---|
| `cs.LG` | Machine Learning | LLM architectures, quantization, inference optimization |
| `cs.AI` | Artificial Intelligence | AI system design, agent frameworks |
| `cs.DC` | Distributed Computing | Distributed inference, model parallelism, serving systems |
| `cs.PF` | Performance | Benchmarking, throughput/latency modeling, accelerator evaluation |
| `cs.AR` | Hardware Architecture | Custom accelerators, ASIC/FPGA for inference |
| `cs.CL` | Computation & Language | NLP/LLM core research, decoding strategies |

**arXiv query construction example** (for domain D1 — LLM Disaggregated Inference):
```
search_query=(cat:cs.LG OR cat:cs.AI OR cat:cs.DC OR cat:cs.PF OR cat:cs.AR OR cat:cs.CL)
  AND (ti:"large language model" OR ti:LLM OR ti:transformer)
  AND (abs:inference OR abs:serving)
  AND (abs:"disaggregated inference" OR abs:prefill OR abs:decode OR abs:"KV cache")
&sortBy=submittedDate&sortOrder=descending&max_results=100
```

**Daily scan strategy**:
1. Query each domain (D1–D6) separately against arXiv API with category filters.
2. Merge results, deduplicate by arXiv ID.
3. Filter to papers submitted within the last 24 hours (or since last scan timestamp).
4. Pass candidates to the scoring pipeline.

### Profile YAML — Source Entry Example (arXiv)

```yaml
sources:
  - label: "arXiv"
    type: api
    adapter: arxiv
    url: "http://export.arxiv.org/api/query"
    enabled: true
    default: true
    config:
      categories:
        - cs.LG
        - cs.AI
        - cs.DC
        - cs.PF
        - cs.AR
        - cs.CL
      max_results_per_query: 100
      rate_limit_seconds: 3
      lookback_hours: 24
```

---

### S2: Semantic Scholar (Default — Enabled) 🔲 v0.2

| Property | Value |
|---|---|
| **Label** | Semantic Scholar |
| **Type** | API |
| **Base URL** | `https://api.semanticscholar.org/graph/v1` |
| **Adapter** | `SemanticScholarAdapter` — uses the S2 Academic Graph API |
| **Python client** | Direct `httpx` calls (no official PyPI client needed; API is simple REST+JSON) |
| **Auth** | Optional API key via `S2_API_KEY` env var or profile config. Anonymous: 10 req/5min. Authenticated: 100 req/5min. |
| **Rate limits** | 10 requests per 5 minutes (anonymous), 100 per 5 minutes (with API key). Adapter must implement backoff. |
| **Query mapping** | Domain boolean queries are simplified to keyword search: extract key terms from each domain query, submit as `query` parameter to `/paper/search`. S2 does not support full boolean syntax — rely on keyword pre-filter post-fetch for precision. |
| **Sort** | `sort=publicationDate:desc` for newest-first |
| **Pagination** | `offset` + `limit` parameters; fetch in pages of 100 (max `limit=100`) |
| **Fields** | Request: `title,authors,abstract,url,externalIds,publicationDate,venue,citationCount` |
| **Dedup key** | S2 Paper ID (unique), plus DOI from `externalIds` for cross-source dedup |

**S2 query construction example** (for domain D1):
```
GET /paper/search?query=large+language+model+disaggregated+inference+KV+cache
    &fields=title,authors,abstract,url,externalIds,publicationDate,venue,citationCount
    &sort=publicationDate:desc
    &limit=100
    &year=2026-
```

**Daily scan strategy**:
1. Extract key terms from each domain query (drop boolean operators, keep quoted phrases as compound terms).
2. Query S2 API with combined terms, limit to current year or last N days.
3. Merge results, deduplicate by S2 Paper ID and DOI.
4. Apply keyword pre-filter (full boolean evaluation) to compensate for S2's limited query syntax.
5. Pass survivors to the scoring pipeline.

### Profile YAML — Source Entry Example (Semantic Scholar)

```yaml
  - label: "Semantic Scholar"
    type: api
    adapter: semantic_scholar
    url: "https://api.semanticscholar.org/graph/v1"
    enabled: true
    default: true
    config:
      api_key_env: "S2_API_KEY"
      fields: "title,authors,abstract,url,externalIds,publicationDate,venue,citationCount"
      max_results_per_query: 100
      rate_limit_requests: 10
      rate_limit_window_seconds: 300
      lookback_hours: 24
```

---

### S3: RSS/Atom Feeds (User-Defined) 🔲 v0.2

| Property | Value |
|---|---|
| **Label** | User-defined (e.g., "Google AI Blog", "OpenAI Research") |
| **Type** | RSS |
| **Adapter** | `RssAdapter` — generic RSS/Atom feed parser |
| **Python client** | `feedparser` PyPI package (handles RSS 2.0, Atom 1.0, and variants) |
| **Auth** | None (public feeds). Future: HTTP basic auth for private feeds. |
| **Rate limits** | Respect `Cache-Control` and `ETag` headers. Minimum 60-second interval between fetches of the same feed. |
| **Query mapping** | No query translation — RSS feeds are fetched in full. Keyword pre-filter is applied post-fetch to select relevant entries. |
| **Dedup key** | Entry `guid` or `link` URL (whichever is available), falling back to title fuzzy match |

**Feed entry → Publication mapping**:

| RSS/Atom Field | Publication Field |
|---|---|
| `title` | `title` |
| `author` / `dc:creator` | `authors` (split on `,` or `;`) |
| `summary` / `description` / `content:encoded` | `abstract` (HTML stripped, truncated to 2000 chars) |
| `link` | `url` |
| `published` / `updated` | `publication_date` |
| `guid` / `id` | `source_id` (for dedup) |

**Detection heuristic** (for `source-detect`):
1. Fetch URL with `Accept: application/rss+xml, application/atom+xml, text/xml, application/xml`.
2. If response Content-Type contains `xml` or `rss` or `atom`, parse as feed.
3. If HTML response, scan for `<link rel="alternate" type="application/rss+xml">` — follow that URL.
4. If `feedparser.parse()` returns entries with `title` and `link`, classify as RSS.
5. Otherwise, classify as `web` type.

### Profile YAML — Source Entry Example (RSS)

```yaml
  - label: "Google AI Blog"
    type: rss
    adapter: rss
    url: "https://blog.google/technology/ai/rss/"
    enabled: true
    default: false
    user_added: true
    added_date: "2026-04-05"
    config:
      respect_etag: true
      min_fetch_interval_seconds: 60
```

---

### S4: Generic Web Scraper (User-Defined — Experimental) 🔲 v0.2

| Property | Value |
|---|---|
| **Label** | User-defined (e.g., "NVIDIA Research", "OpenAI Blog") |
| **Type** | Web |
| **Adapter** | `WebAdapter` — heuristic HTML scraper |
| **Python client** | `httpx` for fetching, `beautifulsoup4` for parsing |
| **Auth** | None (public pages only) |
| **Rate limits** | 5-second delay between page fetches. Respect `robots.txt` (via `robotparser`). |
| **Query mapping** | No query translation — fetch full page, extract publication-like items, apply keyword pre-filter post-fetch. |
| **Dedup key** | Extracted URL of each item, falling back to title fuzzy match |

**Extraction heuristics** (ordered by reliability):
1. **JSON-LD**: Look for `<script type="application/ld+json">` with `@type: ScholarlyArticle`, `BlogPosting`, `Article`.
2. **Structured HTML**: Look for `<article>` elements containing `<h2>`/`<h3>` + `<a>` patterns.
3. **Research listing patterns**: Look for repeated DOM structures (e.g., `.paper-item`, `.research-card`, `li > a + p`).
4. **Fallback**: Extract all `<h2>`/`<h3>` elements with sibling `<a>` links and adjacent text blocks.

**Item → Publication mapping**:

| Extracted Field | Publication Field |
|---|---|
| Heading text | `title` |
| Link `href` | `url` |
| Adjacent paragraph / description | `abstract` (truncated to 2000 chars) |
| Author metadata (if found) | `authors` |
| Date metadata (if found) | `publication_date` |
| Page URL + item index | `source_id` (fallback dedup key) |

> ⚠️ **Experimental**: Web scraping is inherently fragile. Sites change layouts without notice. This adapter is best-effort and should display a warning in scan output: "Web scraper results for {label} may be incomplete — consider using an RSS feed if available."

### Profile YAML — Source Entry Example (Web)

```yaml
  - label: "NVIDIA Research"
    type: web
    adapter: web
    url: "https://www.nvidia.com/en-us/research/publications/"
    enabled: true
    default: false
    user_added: true
    added_date: "2026-04-05"
    config:
      respect_robots_txt: true
      rate_limit_seconds: 5
      extraction_strategy: auto
```

---

## Email Delivery 🔲 v0.2 (NEW)

The system delivers the HTML report via email after each scan (unless `--dry-run` or `--no-email` is specified). Two transport backends are supported: SMTP (primary) and Microsoft Graph API (optional).

### Transport: SMTP (Primary)

| Property | Value |
|---|---|
| **Protocol** | SMTP with STARTTLS (port 587) or SSL/TLS (port 465) |
| **Python client** | `smtplib` (stdlib) + `email.mime` for message construction |
| **Auth** | Username + password (stored in profile or env var `PUBSCOUT_SMTP_PASSWORD`) |
| **Configuration** | `profile.yaml` → `email:` section |

**Message construction**:
- `From`: `email.from` in profile
- `To`: `email.to` in profile (comma-separated for multiple recipients)
- `Subject`: `PubScout Digest — {date} — {count} papers`
- `Content-Type`: `text/html; charset=utf-8` (the generated HTML report)
- `Reply-To`: same as `From`

**Error handling**:
- Connection refused → log error, save report to file, warn user
- Auth failure → log error with hint to check credentials, save report to file
- Send failure → retry once after 5 seconds, then save to file

### Transport: Microsoft Graph API (Optional)

| Property | Value |
|---|---|
| **Endpoint** | `https://graph.microsoft.com/v1.0/me/sendMail` |
| **Auth** | OAuth2 device-code flow (interactive) or client credentials (headless) |
| **Python client** | `httpx` for REST calls, `msal` for token management |
| **Scopes** | `Mail.Send` |
| **Configuration** | `profile.yaml` → `email.transport: graph` + `email.graph_client_id` |

**Token management**:
- On first use, run device-code flow and cache the refresh token at `~/.pubscout/graph_token.json`.
- On subsequent runs, use the cached refresh token silently.
- If refresh token expires, re-prompt with device-code flow.

> **Design decision**: SMTP is the primary transport because it works everywhere and requires no Azure AD setup. Graph API is optional for Microsoft 365 users who prefer it or need it for compliance.

### Profile YAML — Email Configuration

```yaml
email:
  transport: smtp           # "smtp" or "graph"
  from: "user@example.com"
  to: "user@example.com"    # comma-separated for multiple
  # SMTP settings (when transport: smtp)
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  smtp_use_tls: true
  smtp_username: "user@example.com"
  smtp_password_env: "PUBSCOUT_SMTP_PASSWORD"  # read from env var
  # Graph settings (when transport: graph)
  graph_client_id: ""       # Azure AD app registration client ID
  graph_tenant_id: ""       # Azure AD tenant ID (or "common")
```

### CLI Integration

- `pubscout scan` — sends email after report generation (default)
- `pubscout scan --dry-run` — saves report to file, no email
- `pubscout scan --no-email` — runs pipeline, saves report, skips email delivery
- `pubscout email test` — sends a test email with a sample report to verify configuration

---

## Feedback System ✅ Implemented v0.2 (REDESIGNED in v3)

The feedback loop enables users to rate publications in the digest, improving future scoring. The system uses a **local-only, self-contained approach** — no server required. Feedback is collected directly in the HTML report via inline JavaScript, exported as JSON, and imported via CLI.

> **Design decision** (v3 — supersedes v2): The HTTP feedback server approach was abandoned. Rationale: browser security policies (CORS), timing issues with subprocess auto-start, and the requirement for a running server created poor UX. The local-only approach works offline, requires no server, and persists feedback across page refreshes via `localStorage`.

### Inline Report Feedback (Primary)

The HTML report embeds self-contained JavaScript that:

1. **Captures clicks** — 👍/👎 buttons per publication toggle visual state (active/dimmed)
2. **Persists locally** — Ratings are stored in `localStorage` with key `pubscout_feedback_YYYY-MM-DD`
3. **Survives refresh** — On page load, saved ratings are restored from `localStorage`
4. **Exports JSON** — A floating "Save feedback.json" bar appears after any rating; clicking it downloads a JSON file via Blob URL

**Exported JSON format:**
```json
[
  {"publication_id": "uuid", "signal": "positive", "timestamp": "2026-04-06T01:00:00.000Z"},
  {"publication_id": "uuid", "signal": "negative", "timestamp": "2026-04-06T01:00:05.000Z"}
]
```

**Report footer** includes usage hint: `Click 👍/👎 then Save & import with: pubscout feedback import feedback.json`

### Feedback CLI Commands

```
pubscout feedback record <publication-id> <up|down> [--note "Optional note"]
pubscout feedback list [--limit 20] [--signal positive|negative]
pubscout feedback import <file>
```

- `feedback record <id> up/down` — records a feedback signal directly to SQLite
- `feedback list` — shows recent feedback entries (date, pub title, signal, note)
- `feedback import <file>` — reads a JSON file exported from the HTML report, saves each entry to SQLite, prints summary (N positive, N negative, N skipped)

### Feedback → Scoring Integration

The existing LLM scorer prompt already supports feedback injection (implemented in v0.1 `scorer.py`). The integration works as follows:

1. Before each LLM scoring call, query `database.get_positive_examples(limit=5)` and `database.get_negative_examples(limit=5)`.
2. If examples exist, append to the scoring prompt:
   - "The user has previously rated these publications as RELEVANT: [titles]"
   - "The user has previously rated these publications as NOT RELEVANT: [titles]"
3. The LLM uses these examples to calibrate its relevance assessment.

**Golden-set test requirement** (per constitution): A test suite with 10 known-relevant and 10 known-irrelevant publications must verify that feedback injection measurably shifts scores in the expected direction.

---

## Interactive Init Wizard 🔲 v0.2 (NEW)

The current `pubscout init` creates a default profile non-interactively. The v0.2 wizard provides a guided setup using `rich` console prompts.

### Wizard Flow

```
$ pubscout init

🔬 PubScout Setup Wizard

Step 1/5 — Research Domains
  The following default domains are pre-configured:
  [1] ✅ LLM Disaggregated Inference
  [2] ✅ Inference Performance Modeling
  [3] ✅ Inference Cost Efficiency
  [4] ✅ Low-Precision & Quantization
  [5] ✅ Efficient Compute Kernels
  [6] ✅ RL-Based Code & Kernel Generation
  
  Toggle domains (enter numbers, comma-separated), or press Enter to keep defaults: 
  Add custom domain? (label + boolean query, or blank to skip):

Step 2/5 — Default Sources
  Enable built-in sources:
  [1] ✅ arXiv (academic preprints)
  [2] ✅ Semantic Scholar (academic papers)
  Toggle (enter numbers), or press Enter to keep defaults:

Step 3/5 — Custom Sources
  Enter websites/URLs to monitor (one per line, blank to finish):
  > https://blog.google/technology/ai/
    → Detected: RSS feed (Google AI Blog) ✅
  > https://openai.com/research
    → Detected: Web page (auto-scrape) ⚠️
  > 

Step 4/5 — Email Delivery
  Email address for daily digest: user@example.com
  Email transport: [SMTP / Microsoft Graph / Skip for now]
  (If SMTP): SMTP host: smtp.gmail.com
  (If SMTP): SMTP port [587]: 
  Test email delivery? [Y/n]:

Step 5/5 — LLM Scoring
  OpenAI API key (or press Enter to skip — keyword-only scoring):
  API base URL [https://api.openai.com/v1]: 
  Model [gpt-4o-mini]: 
  Test API connection? [Y/n]:

✅ Profile saved to ~/.pubscout/profile.yaml
   Run `pubscout scan --dry-run` to test your first scan!
```

### Flags

- `pubscout init` — interactive wizard (default)
- `pubscout init --non-interactive` — create default profile without prompts (current v0.1 behavior, preserved for scripting)
- `pubscout init --sources-file urls.txt` — import URLs from file during init (FR-003c)

---

## Source Management CLI 🔲 v0.2 (NEW)

Full CRUD operations for source management. Extends the existing read-only `pubscout sources` (list) command.

### Commands

```
pubscout sources                          # List all sources (existing v0.1)
pubscout sources add <url> [OPTIONS]      # Add a new source
pubscout sources remove <label>           # Remove a source by label
pubscout sources test <url-or-label>      # Test connectivity and extraction
pubscout sources import <file>            # Batch import URLs from file
pubscout sources export                   # Export source URLs to stdout
pubscout sources enable <label>           # Enable a disabled source
pubscout sources disable <label>          # Disable a source without removing
```

### `sources add` Options

| Option | Description |
|---|---|
| `--name TEXT` | Human-readable label (default: auto-generated from domain name) |
| `--type [api\|rss\|web]` | Override auto-detection |
| `--no-detect` | Skip type auto-detection (use `--type` value as-is) |

**Behavior**:
1. If `<url>` is provided, probe it using `source-detect` module.
2. Display detected type + sample items.
3. If no `--name`, prompt user for a label (default: extracted domain name).
4. Add to profile.yaml under `sources:` with `user_added: true`.
5. If `<url>` is omitted, enter interactive mode: prompt for URLs one at a time.

### `sources test` Output

```
$ pubscout sources test https://blog.google/technology/ai/rss/

Source: https://blog.google/technology/ai/rss/
  Reachable:    ✅ Yes (HTTP 200, 142ms)
  Detected type: RSS (Atom 1.0)
  Feed title:   Google AI Blog
  Sample items:
    1. "Introducing Gemini 2.0 Flash Thinking" (2026-03-28)
    2. "Advances in multimodal reasoning" (2026-03-25)
    3. "Efficient inference at scale" (2026-03-22)
  Estimated items/fetch: ~15
```

### `sources import` Format

One URL per line. Lines starting with `#` are comments. Blank lines are ignored. Duplicate URLs are skipped with a warning.

```
# Research blogs
https://blog.google/technology/ai/rss/
https://openai.com/research

# Conference feeds
https://proceedings.neurips.cc/rss
```

---

## Domain Management CLI 🔲 v0.2 (NEW)

Extends the existing read-only `pubscout domains` (list) command.

### Commands

```
pubscout domains                              # List all domains (existing v0.1)
pubscout domains add <label> <query>          # Add a new domain
pubscout domains remove <label>               # Remove a domain by label
pubscout domains enable <label>               # Enable a disabled domain
pubscout domains disable <label>              # Disable a domain without removing
```

### `domains add` Validation

Before saving, the system MUST parse the query string through the boolean query parser. If parsing fails, display the parse error and reject the addition.

```
$ pubscout domains add "Custom Domain" '("deep learning" OR "neural network") AND (optimization OR training)'
✅ Domain "Custom Domain" added and enabled.

$ pubscout domains add "Bad Query" 'AND OR broken'
❌ Parse error: unexpected token 'OR' at position 4. Check query syntax.
```

---

## Relevance Tuning CLI ✅ Implemented v0.2

CLI commands to modify scoring and scan configuration in `profile.yaml` without manual YAML editing.

### Commands

```
pubscout config show                          # Show current scanning/scoring config
pubscout config threshold <value>             # Set score threshold (1.0-10.0)
pubscout config scan-range <days>             # Set scan time range (1-365 days, default: 7)
pubscout config exclude-add <keyword>         # Add an exclude keyword
pubscout config exclude-remove <keyword>      # Remove an exclude keyword
pubscout config include-add <keyword>         # Add an include (required) keyword
pubscout config include-remove <keyword>      # Remove an include keyword
pubscout config model <model-name>            # Set LLM model name
pubscout config api-key <key>                 # Set LLM API key
```

### Example

```
$ pubscout config show
  Scanning
    Scan range: 7 day(s)
  Scoring
    Threshold:        5.0
    Include keywords: (none)
    Exclude keywords: (none)
  LLM
    Provider:         openai
    Model:            gpt-4o-mini
    API key:          not set

$ pubscout config scan-range 14
✓ Scan range set to 14 day(s)

$ pubscout config threshold 7.0
✓ Relevance threshold set to 7.0

$ pubscout config exclude-add "survey"
✓ Added "survey" to exclude keywords.
```

---

## Statistics CLI 🔲 v0.2 (NEW)

Analytics dashboard querying existing SQLite tables.

### Commands

```
pubscout stats [--since YYYY-MM-DD]
```

### Output

```
$ pubscout stats

📊 PubScout Statistics

  Period:                  All time (since 2026-04-02)
  Total scans:             14
  Total publications seen: 823
  Publications reported:   187 (22.7%)
  
  Feedback:
    Total signals:         42
    Positive (👍):          31 (73.8%)
    Negative (👎):          11 (26.2%)
  
  Top-scoring domains:
    1. LLM Disaggregated Inference     — 47 reported papers
    2. Low-Precision & Quantization    — 38 reported papers
    3. Inference Cost Efficiency        — 29 reported papers
  
  Sources:
    arXiv                              — 743 fetched, 162 reported
    Semantic Scholar                   — 80 fetched, 25 reported
```

---

## Profile Migration 🔲 v0.2 (NEW)

### Schema Versioning

Profile YAML includes a `version` field:

```yaml
version: 2
domains: [...]
sources: [...]
email: {...}
```

### Migration Rules

1. On load, read `version` field (absent = version 1).
2. If version < current schema version, auto-migrate:
   - **v1 → v2**: Add `email:` section with empty defaults, add `version: 2`, add `user_added` and `added_date` fields to sources.
3. Before migration, back up existing profile: `profile.yaml` → `profile.yaml.bak.{timestamp}`.
4. After migration, log: "Profile migrated from v1 to v2. Backup saved at profile.yaml.bak.{timestamp}."
5. If migration fails, abort and leave original profile untouched.

---

## Scheduler Integration 🔲 v0.2 (NEW)

PubScout is a CLI tool that runs once per invocation (per constitution). Scheduling is handled by the OS scheduler.

### `pubscout schedule show`

Prints recommended scheduling commands based on detected OS:

**Linux/macOS (cron)**:
```
$ pubscout schedule show

Recommended cron entry (daily at 8:00 AM):
  0 8 * * * cd /home/user && pubscout scan >> ~/.pubscout/cron.log 2>&1

To install:
  crontab -e   # then paste the line above

Note: Ensure PUBSCOUT_SMTP_PASSWORD and OPENAI_API_KEY are set in your cron environment.
Start the feedback server separately: pubscout feedback serve --timeout 7200
```

**Windows (Task Scheduler)**:
```
$ pubscout schedule show

Recommended Task Scheduler command:
  schtasks /create /tn "PubScout Daily Scan" /tr "pubscout scan" /sc daily /st 08:00

To view: schtasks /query /tn "PubScout Daily Scan"
To delete: schtasks /delete /tn "PubScout Daily Scan" /f
```

This command is informational only — it does NOT create the scheduled task. The user must run the printed command themselves.

---

## User Scenarios & Testing

### User Story 1 — Configure Domains, Sources, and Run First Scan (Priority: P1)

A new user installs PubScout, defines their interests (e.g., "AI/ML research papers", "AI accelerators", "GPUs"), provides a list of web resources/sites they want scanned, and runs the first scan. The init wizard has a **dedicated step for source configuration** where the user can supply URLs of websites, blogs, RSS feeds, conference pages, or any web resource they want monitored. The system also offers built-in defaults (arXiv, Semantic Scholar) that the user can opt into. The result is a fully configured profile with both domain interests and a concrete list of sources to scan.

**Why this priority**: Without this, nothing else works. This is the end-to-end MVP. User-defined sources are first-class because users often know exactly which sites publish content relevant to their niche.

**Independent Test**: Run `pubscout init` to create a profile, then `pubscout scan --dry-run` to verify the full pipeline produces a report file without sending email.

**v0.1 Status**: ⚠️ Partial — non-interactive init, arXiv-only scan, dry-run works. Missing: interactive wizard, source URL input, Semantic Scholar.

**Acceptance Scenarios**:

1. **Given** no existing profile, **When** user runs `pubscout init`, **Then** an interactive wizard walks through: (a) domains — present the 6 default domain queries and let user enable/disable/edit each, plus add custom domains, (b) **web sources — prompt asks "Enter websites/URLs to monitor (one per line, blank to finish):"**, (c) offer to enable default sources (arXiv, Semantic Scholar), (d) email address, (e) LLM API key — saving all to `~/.pubscout/profile.yaml`.
2. **Given** user provides 3 URLs during init (e.g., `https://blog.google/technology/ai/`, `https://openai.com/research`, `https://nvidia.com/en-us/research/`), **When** profile is saved, **Then** all 3 URLs appear in `profile.yaml` under `sources:` with auto-detected type (rss/web) and user-provided label (or auto-generated from domain name).
3. **Given** user provides a URL during init, **When** the system probes the URL, **Then** it auto-detects whether the URL is an RSS/Atom feed, an API endpoint, or a generic web page — and configures the appropriate source adapter.
4. **Given** a valid profile with 5 sources (2 default + 3 user-defined), **When** user runs `pubscout scan`, **Then** the system fetches from all 5 sources, deduplicates, scores relevance, and generates an HTML report.
5. **Given** a valid profile, **When** user runs `pubscout scan --dry-run`, **Then** the system performs the full pipeline but writes the report to a local file instead of sending email. ✅ Implemented v0.1
6. **Given** a source URL is unreachable, **When** scan runs, **Then** the pipeline logs a warning, skips that source, and continues with remaining sources. ✅ Implemented v0.1
7. **Given** no new publications are found, **When** scan runs, **Then** the system logs "no new publications" and does not send an empty email. ✅ Implemented v0.1
8. **Given** user runs `pubscout init --sources-file urls.txt`, **When** `urls.txt` contains one URL per line, **Then** all URLs are imported into the profile as sources (batch import for users with a large list).

---

### User Story 2 — Receive Daily Email Digest (Priority: P1)

The user receives a well-formatted daily email with new relevant publications. Each entry includes: title, authors, abstract snippet, relevance score, source, publication date, and a direct link. Each entry also has thumbs-up/down feedback links.

**Why this priority**: The email is the primary value delivery mechanism.

**Independent Test**: Generate a report from fixture data and verify the HTML output contains all required fields, proper formatting, and functional feedback links.

**v0.1 Status**: ⚠️ Partial — HTML report generated and saved to file. Missing: actual email delivery via SMTP or Graph API.

**Acceptance Scenarios**:

1. **Given** 15 new relevant publications found, **When** report is generated, **Then** the email contains all 15 items sorted by relevance score (highest first), each with title, authors (max 3 + "et al."), abstract (first 200 chars), relevance score (1-10), source name, date, and clickable link. ✅ Implemented v0.1
2. **Given** a generated report, **When** email is sent, **Then** each publication entry has a 👍 and 👎 link that records feedback to the local feedback store when clicked.
3. **Given** publications from 4 different sources, **When** report is generated, **Then** items are interleaved by relevance score (not grouped by source). ✅ Implemented v0.1
4. **Given** a daily scan finds 0 new relevant items (but found items that scored below threshold), **When** report would be generated, **Then** the system sends a brief summary: "Scanned X sources, found Y items, none met relevance threshold. Adjust keywords or lower threshold?" ✅ Implemented v0.1

---

### User Story 3 — Provide Feedback to Refine Relevance (Priority: P2)

The user clicks thumbs-up or thumbs-down on publications in the digest. The system records this feedback and uses it to improve future relevance scoring — surfacing more publications like the upvoted ones and fewer like the downvoted ones.

**Why this priority**: This is the learning loop that makes the system increasingly valuable over time, but the system works (with static relevance) without it.

**Independent Test**: Inject 10 feedback signals (5 positive, 5 negative), run a scoring pass on a test set of 20 publications, and verify that scoring shifts measurably toward the positive feedback patterns.

**v0.1 Status**: ⚠️ Partial — Database schema supports feedback storage, LLM scorer has prompt injection for feedback examples. Missing: HTTP server to receive clicks, CLI command to record feedback.

**Acceptance Scenarios**:

1. **Given** a user clicks 👍 on a publication, **When** the feedback endpoint processes the click, **Then** the feedback is recorded in SQLite with: publication_id, timestamp, signal=positive, and the publication's metadata (domain, keywords, source).
2. **Given** 10+ positive feedback signals in a domain, **When** the next scan runs, **Then** the LLM scoring prompt includes a summary of positively-rated examples as "user prefers publications like these".
3. **Given** 10+ negative feedback signals for a keyword, **When** the next scan runs, **Then** publications matching that keyword pattern receive a scoring penalty.
4. **Given** a user has provided no feedback yet, **When** scan runs, **Then** scoring uses only the base keyword + LLM approach with no feedback-derived adjustments. ✅ Implemented v0.1

---

### User Story 4 — Manage Source List (Priority: P2)

The user can add, remove, list, test, and import/export their configured publication sources at any time after setup. Default sources (arXiv, Semantic Scholar) are always available but can be disabled. Users can add any web resource — RSS feed URLs, blog pages, conference proceedings, news sites, institutional research pages, or API endpoints. The system auto-detects the best fetching strategy for each URL.

**Why this priority**: The source list is the foundation of what gets scanned. Users must be able to curate it easily. The init wizard captures the initial list, but ongoing management is essential as interests evolve.

**Independent Test**: Run `pubscout sources add <url>`, `pubscout sources list`, `pubscout sources test <url>`, `pubscout sources remove <url>` and verify profile.yaml is updated correctly and test output shows connectivity + content extraction results.

**v0.1 Status**: ⚠️ Partial — `pubscout sources` lists configured sources. Missing: add, remove, test, import, export, enable, disable.

**Acceptance Scenarios**:

1. **Given** a new profile, **When** user lists sources, **Then** default sources are shown: arXiv API, Semantic Scholar API — plus any user-defined sources from init. ⚠️ arXiv only in v0.1
2. **Given** user runs `pubscout sources add https://blog.google/technology/ai/`, **When** the URL is probed, **Then** it is auto-classified (RSS/Atom feed → rss adapter; otherwise → web-scrape adapter) and added to profile with a user-editable label.
3. **Given** user runs `pubscout sources add https://example.com/papers --name "Example Lab Papers" --type rss`, **When** the URL is added, **Then** it uses the user-specified name and type override (no auto-detection).
4. **Given** user runs `pubscout sources test https://blog.google/technology/ai/`, **When** the URL is probed, **Then** the system reports: reachable (yes/no), detected type (rss/web/api), sample items extracted (show 3 titles), and estimated fetch rate.
5. **Given** user runs `pubscout sources import urls.txt`, **When** the file contains one URL per line, **Then** all URLs are added to the profile (duplicates skipped with a warning).
6. **Given** user runs `pubscout sources export`, **Then** all source URLs are written to stdout (one per line) for backup or sharing.
7. **Given** user removes a default source, **When** scan runs, **Then** that source is skipped.
8. **Given** user runs `pubscout sources add` with no URL, **Then** an interactive prompt asks for URLs one at a time (same UX as the init wizard source step).

---

### User Story 5 — Tune Relevance Settings (Priority: P3)

The user can adjust relevance scoring parameters: minimum score threshold (1-10), scoring model, and whether to include/exclude specific keywords as hard filters.

**Why this priority**: Power-user feature; defaults should work for most users.

**Independent Test**: Modify threshold in profile, run scan on fixture data, verify items below threshold are excluded from report.

**v0.1 Status**: ⚠️ Partial — Scoring engine supports threshold, include/exclude keywords. Missing: CLI commands to manage them.

**Acceptance Scenarios**:

1. **Given** threshold set to 7, **When** scan scores a publication at 6.5, **Then** it is excluded from the report. ✅ Implemented v0.1
2. **Given** user adds "survey" as an excluded keyword, **When** a publication title contains "survey", **Then** it is excluded regardless of score. ✅ Implemented v0.1
3. **Given** user adds "transformer" as a required keyword, **When** a publication has no mention of "transformer" in title or abstract, **Then** it receives a scoring penalty of -3. ✅ Implemented v0.1

---

### User Story 6 — View Scan History and Stats (Priority: P3)

The user can review past scan results, publication history, and feedback statistics via CLI.

**Why this priority**: Useful for debugging and understanding system behavior, but not critical for daily operation.

**Independent Test**: After 3 scan runs, `pubscout history` shows summaries of all 3 runs with item counts.

**v0.1 Status**: ⚠️ Partial — `pubscout history` shows last 10 scans. Missing: `pubscout stats` with analytics.

**Acceptance Scenarios**:

1. **Given** 5 completed scans, **When** user runs `pubscout history`, **Then** output shows: date, sources scanned, items found, items above threshold, items reported. ✅ Implemented v0.1
2. **Given** feedback has been provided, **When** user runs `pubscout stats`, **Then** output shows: total publications seen, total feedback given, positive/negative ratio, top-rated domains, most-rejected keywords.

---

### Edge Cases

- **Duplicate publication across sources**: Same paper appears on arXiv and Semantic Scholar → deduplicate by DOI, then by title similarity (>90% fuzzy match). ✅ Implemented v0.1
- **LLM API unreachable**: Fall back to keyword-only scoring with a warning in the report header. ✅ Implemented v0.1
- **Extremely high volume**: If a source returns >200 items in one scan, paginate and apply keyword pre-filter before LLM scoring to control API costs. ✅ Implemented v0.1
- **Malformed RSS feed**: Log error, skip source, continue pipeline.
- **Feedback endpoint unavailable**: Feedback links should degrade gracefully — if the local server isn't running, the link shows a user-friendly error page suggesting CLI alternative: `pubscout feedback <pub-id> up/down`.
- **Profile migration**: If profile schema changes between versions, the system auto-migrates with a backup of the old profile.

---

## Requirements

### Functional Requirements

| Req | Description | v0.1 | v0.2 Task |
|---|---|---|---|
| **FR-001** | User-defined interest domains as structured boolean queries | ✅ | — |
| **FR-001a** | Keyword pre-filter (boolean eval, no LLM) | ✅ | — |
| **FR-001b** | Domain context injection into LLM scorer | ✅ | — |
| **FR-001c** | 6 default domain queries, user-customizable | ✅ | — |
| **FR-002** | Fetch from arXiv, Semantic Scholar, and RSS feeds | ⚠️ arXiv only | `semantic-scholar`, `rss-adapter` |
| **FR-002a** | arXiv query translation (ti:/abs:/cat:) | ✅ | — |
| **FR-002b** | arXiv rate limiting (3s delay, pages of ≤100) | ✅ | — |
| **FR-003** | Web scraping for non-RSS/API URLs | ❌ | `web-adapter` |
| **FR-003a** | Accept user URLs during init and sources add | ❌ | `init-wizard`, `sources-add` |
| **FR-003b** | Auto-detect source type (RSS/API/web) | ❌ | `source-detect` |
| **FR-003c** | Batch import URLs from file | ❌ | `sources-io` |
| **FR-003d** | `sources test <url>` command | ❌ | `sources-test` |
| **FR-004** | Dedup by DOI + title fuzzy match | ✅ | — |
| **FR-005** | Two-pass scoring (keyword + LLM) | ✅ | — |
| **FR-006** | HTML email digest sorted by score | ⚠️ Report only | `email-smtp` |
| **FR-007** | Per-item feedback links (👍/👎) | ✅ Links exist | `feedback-server` |
| **FR-008** | Record feedback, incorporate into scoring | ⚠️ DB ready | `feedback-server`, `feedback-cli` |
| **FR-009** | `--dry-run` mode | ✅ | — |
| **FR-010** | Structured pipeline logging | ✅ | — |
| **FR-011** | Persist publication history in SQLite | ✅ | — |
| **FR-012** | Configurable relevance threshold | ✅ | `relevance-tuning` (CLI) |
| **FR-013** | Include/exclude keyword hard filters | ✅ | `relevance-tuning` (CLI) |
| **FR-014** | Graceful degradation | ✅ | `error-resilience` (review) |
| **FR-015** | CLI: init, scan, sources, feedback, history, stats | ⚠️ Partial | Multiple v0.2 tasks |
| **FR-016** | Lightweight feedback HTTP server | ❌ | `feedback-server` |

### Non-Functional Requirements

| Req | Description | v0.1 |
|---|---|---|
| **NFR-001** | Full scan ≤5 min for ≤500 pubs | ✅ (22s for 550 pubs) |
| **NFR-002** | LLM cost bounded by pre-filter | ✅ |
| **NFR-003** | All data local | ✅ |
| **NFR-004** | Windows 10+, macOS 12+, Linux | ⚠️ Untested on macOS/Linux |
| **NFR-005** | YAML config, human-readable | ✅ |

### Key Entities

- **UserProfile**: Domains (structured boolean queries with labels), source list, email config, LLM config, scoring thresholds, include/exclude filters.
- **Domain**: Label, boolean query string, enabled flag. Evaluated in two passes: keyword pre-filter (boolean text match) and LLM context injection.
- **Publication**: Title, authors, abstract, URL, DOI, source, publication_date, fetch_date, relevance_score, reported (bool).
- **FeedbackSignal**: Publication ID, timestamp, signal (positive/negative), user_notes (optional).
- **ScanRun**: Run ID, timestamp, sources_checked, items_fetched, items_scored, items_reported, errors, duration.
- **Source**: Type (api/rss/web), URL, user-defined label, enabled, last_fetched, adapter_class, auto_detected_type, user_added (bool — distinguishes default vs. user-provided), added_date.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: A new user can go from zero to first email digest in under 10 minutes (install + init + first scan).
- **SC-002**: Daily scan reliably delivers ≥80% of relevant new publications from configured sources (precision measured against manual review of 3 consecutive days).
- **SC-003**: After 2 weeks of daily feedback (≥5 signals/day), false-positive rate in the digest drops by ≥30% compared to week 1.
- **SC-004**: System completes daily scan of 5 sources in under 3 minutes on a standard workstation.
- **SC-005**: Zero manual intervention required for daily operation after initial setup (no babysitting the scheduler).

---

## Assumptions

- User has Python 3.11+ and `uv` installed.
- User has access to an OpenAI-compatible LLM API endpoint (Azure OpenAI or OpenAI; API key required for LLM scoring, optional for keyword-only mode).
- User has an email account accessible via SMTP or Microsoft Graph API for sending digests (optional — reports can be saved to file without email).
- arXiv and Semantic Scholar APIs are publicly available and rate-limit-friendly for daily queries.
- Daily publication volume per user profile is <1000 items (pre-filter), <100 items (post-filter for LLM scoring).
- The feedback mechanism uses a lightweight local HTTP server; the user's email client must be able to open localhost URLs (alternative: CLI feedback command).
- Mobile support is out of scope for v1.
- Multi-user support is out of scope for v1 (single-user, single-profile).

---

## Design Decisions (Resolved Open Questions)

1. **Feedback server lifecycle** → **On-demand**. The server runs via `pubscout feedback serve` and auto-stops after configurable inactivity timeout (default: 1 hour). Rationale: avoids persistent background resource consumption while keeping UX simple for digest reading sessions. CLI fallback (`pubscout feedback <id> up/down`) provides offline alternative.

2. **LLM prompt strategy** → **Full abstract**. The scoring prompt includes the complete abstract (current v0.1 behavior). Rationale: token cost is bounded by the keyword pre-filter limiting LLM calls to ≤100 items per scan. Full abstract provides meaningfully better relevance assessment than title-only.

3. **Source discovery** → **Explicit configuration only (v1)**. The system does NOT auto-discover sources. Users explicitly add sources via `init` wizard, `sources add`, or `sources import`. Rationale: auto-discovery adds complexity and unpredictability. Users in niche research areas know their sources. Consider for v2+ if demand exists.

4. **Digest frequency** → **Daily only (v1)**. The scheduling cadence is controlled by the OS scheduler (cron/Task Scheduler). The system runs once per invocation regardless of frequency. Users who want weekly digests can schedule accordingly. No in-app frequency configuration needed.

5. **Rate limiting** → **Backoff + retry with configurable delays**. Each adapter implements its own rate limiting strategy: arXiv (3s delay, courtesy), Semantic Scholar (backoff per API limits), RSS (respect Cache-Control/ETag), Web (5s delay + robots.txt). Failed requests retry once after exponential backoff, then skip with a logged warning.

---

## Open Questions (v2)

1. **Graph API app registration**: Should PubScout ship a pre-registered Azure AD app ID for Graph API email, or require users to create their own? Pre-registered simplifies UX but creates a dependency on the app publisher.
2. **Web scraper reliability**: Should the web adapter include a "last successful extraction" metric to auto-disable sources that consistently fail? What's the failure threshold?
3. **Feedback decay**: Should older feedback signals carry less weight in LLM prompts? If so, what's the decay curve?

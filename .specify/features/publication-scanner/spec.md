# Feature Specification: Publication Scanner Agent

**Feature Branch**: `001-publication-scanner`  
**Created**: 2026-03-26  
**Status**: Draft  
**Input**: Agentic system that scans web resources daily for new publications in user-defined domains, filters by relevance, generates email digests, and refines via user feedback.

---

## System Overview

**PubScout** is a CLI-driven agentic pipeline that:
1. Accepts user-defined domains, keywords, and (optionally) source URLs
2. Scans configured sources daily (arXiv, Semantic Scholar, RSS feeds, web pages)
3. Deduplicates against previously seen publications
4. Scores each new publication for relevance using keyword matching + LLM analysis
5. Generates an HTML email digest with thumbs-up/down feedback links per item
6. Collects feedback to refine future relevance scoring

The system runs as a scheduled CLI invocation — it is **not** a long-running service.

---

## User Scenarios & Testing

### User Story 1 — Configure Domains, Sources, and Run First Scan (Priority: P1)

A new user installs PubScout, defines their interests (e.g., "AI/ML research papers", "AI accelerators", "GPUs"), provides a list of web resources/sites they want scanned, and runs the first scan. The init wizard has a **dedicated step for source configuration** where the user can supply URLs of websites, blogs, RSS feeds, conference pages, or any web resource they want monitored. The system also offers built-in defaults (arXiv, Semantic Scholar) that the user can opt into. The result is a fully configured profile with both domain interests and a concrete list of sources to scan.

**Why this priority**: Without this, nothing else works. This is the end-to-end MVP. User-defined sources are first-class because users often know exactly which sites publish content relevant to their niche.

**Independent Test**: Run `pubscout init` to create a profile, then `pubscout scan --dry-run` to verify the full pipeline produces a report file without sending email.

**Acceptance Scenarios**:

1. **Given** no existing profile, **When** user runs `pubscout init`, **Then** an interactive wizard walks through: (a) domains & keywords, (b) **web sources — prompt asks "Enter websites/URLs to monitor (one per line, blank to finish):"**, (c) offer to enable default sources (arXiv, Semantic Scholar), (d) email address, (e) LLM API key — saving all to `~/.pubscout/profile.yaml`.
2. **Given** user provides 3 URLs during init (e.g., `https://blog.google/technology/ai/`, `https://openai.com/research`, `https://nvidia.com/en-us/research/`), **When** profile is saved, **Then** all 3 URLs appear in `profile.yaml` under `sources:` with auto-detected type (rss/web) and user-provided label (or auto-generated from domain name).
3. **Given** user provides a URL during init, **When** the system probes the URL, **Then** it auto-detects whether the URL is an RSS/Atom feed, an API endpoint, or a generic web page — and configures the appropriate source adapter.
4. **Given** a valid profile with 5 sources (2 default + 3 user-defined), **When** user runs `pubscout scan`, **Then** the system fetches from all 5 sources, deduplicates, scores relevance, and generates an HTML report.
5. **Given** a valid profile, **When** user runs `pubscout scan --dry-run`, **Then** the system performs the full pipeline but writes the report to a local file instead of sending email.
6. **Given** a source URL is unreachable, **When** scan runs, **Then** the pipeline logs a warning, skips that source, and continues with remaining sources.
7. **Given** no new publications are found, **When** scan runs, **Then** the system logs "no new publications" and does not send an empty email.
8. **Given** user runs `pubscout init --sources-file urls.txt`, **When** `urls.txt` contains one URL per line, **Then** all URLs are imported into the profile as sources (batch import for users with a large list).

---

### User Story 2 — Receive Daily Email Digest (Priority: P1)

The user receives a well-formatted daily email with new relevant publications. Each entry includes: title, authors, abstract snippet, relevance score, source, publication date, and a direct link. Each entry also has thumbs-up/down feedback links.

**Why this priority**: The email is the primary value delivery mechanism.

**Independent Test**: Generate a report from fixture data and verify the HTML output contains all required fields, proper formatting, and functional feedback links.

**Acceptance Scenarios**:

1. **Given** 15 new relevant publications found, **When** report is generated, **Then** the email contains all 15 items sorted by relevance score (highest first), each with title, authors (max 3 + "et al."), abstract (first 200 chars), relevance score (1-10), source name, date, and clickable link.
2. **Given** a generated report, **When** email is sent, **Then** each publication entry has a 👍 and 👎 link that records feedback to the local feedback store when clicked.
3. **Given** publications from 4 different sources, **When** report is generated, **Then** items are interleaved by relevance score (not grouped by source).
4. **Given** a daily scan finds 0 new relevant items (but found items that scored below threshold), **When** report would be generated, **Then** the system sends a brief summary: "Scanned X sources, found Y items, none met relevance threshold. Adjust keywords or lower threshold?"

---

### User Story 3 — Provide Feedback to Refine Relevance (Priority: P2)

The user clicks thumbs-up or thumbs-down on publications in the digest. The system records this feedback and uses it to improve future relevance scoring — surfacing more publications like the upvoted ones and fewer like the downvoted ones.

**Why this priority**: This is the learning loop that makes the system increasingly valuable over time, but the system works (with static relevance) without it.

**Independent Test**: Inject 10 feedback signals (5 positive, 5 negative), run a scoring pass on a test set of 20 publications, and verify that scoring shifts measurably toward the positive feedback patterns.

**Acceptance Scenarios**:

1. **Given** a user clicks 👍 on a publication, **When** the feedback endpoint processes the click, **Then** the feedback is recorded in SQLite with: publication_id, timestamp, signal=positive, and the publication's metadata (domain, keywords, source).
2. **Given** 10+ positive feedback signals in a domain, **When** the next scan runs, **Then** the LLM scoring prompt includes a summary of positively-rated examples as "user prefers publications like these".
3. **Given** 10+ negative feedback signals for a keyword, **When** the next scan runs, **Then** publications matching that keyword pattern receive a scoring penalty.
4. **Given** a user has provided no feedback yet, **When** scan runs, **Then** scoring uses only the base keyword + LLM approach with no feedback-derived adjustments.

---

### User Story 4 — Manage Source List (Priority: P2)

The user can add, remove, list, test, and import/export their configured publication sources at any time after setup. Default sources (arXiv, Semantic Scholar) are always available but can be disabled. Users can add any web resource — RSS feed URLs, blog pages, conference proceedings, news sites, institutional research pages, or API endpoints. The system auto-detects the best fetching strategy for each URL.

**Why this priority**: The source list is the foundation of what gets scanned. Users must be able to curate it easily. The init wizard captures the initial list, but ongoing management is essential as interests evolve.

**Independent Test**: Run `pubscout sources add <url>`, `pubscout sources list`, `pubscout sources test <url>`, `pubscout sources remove <url>` and verify profile.yaml is updated correctly and test output shows connectivity + content extraction results.

**Acceptance Scenarios**:

1. **Given** a new profile, **When** user lists sources, **Then** default sources are shown: arXiv API, Semantic Scholar API — plus any user-defined sources from init.
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

**Acceptance Scenarios**:

1. **Given** threshold set to 7, **When** scan scores a publication at 6.5, **Then** it is excluded from the report.
2. **Given** user adds "survey" as an excluded keyword, **When** a publication title contains "survey", **Then** it is excluded regardless of score.
3. **Given** user adds "transformer" as a required keyword, **When** a publication has no mention of "transformer" in title or abstract, **Then** it receives a scoring penalty of -3.

---

### User Story 6 — View Scan History and Stats (Priority: P3)

The user can review past scan results, publication history, and feedback statistics via CLI.

**Why this priority**: Useful for debugging and understanding system behavior, but not critical for daily operation.

**Independent Test**: After 3 scan runs, `pubscout history` shows summaries of all 3 runs with item counts.

**Acceptance Scenarios**:

1. **Given** 5 completed scans, **When** user runs `pubscout history`, **Then** output shows: date, sources scanned, items found, items above threshold, items reported.
2. **Given** feedback has been provided, **When** user runs `pubscout stats`, **Then** output shows: total publications seen, total feedback given, positive/negative ratio, top-rated domains, most-rejected keywords.

---

### Edge Cases

- **Duplicate publication across sources**: Same paper appears on arXiv and Semantic Scholar → deduplicate by DOI, then by title similarity (>90% fuzzy match).
- **LLM API unreachable**: Fall back to keyword-only scoring with a warning in the report header.
- **Extremely high volume**: If a source returns >200 items in one scan, paginate and apply keyword pre-filter before LLM scoring to control API costs.
- **Malformed RSS feed**: Log error, skip source, continue pipeline.
- **Feedback endpoint unavailable**: Feedback links should degrade gracefully — if the local server isn't running, the link shows a user-friendly error page suggesting CLI alternative: `pubscout feedback <pub-id> up/down`.
- **Profile migration**: If profile schema changes between versions, the system auto-migrates with a backup of the old profile.

---

## Requirements

### Functional Requirements

- **FR-001**: System MUST support user-defined interest domains as free-text labels with associated keywords.
- **FR-002**: System MUST fetch publications from arXiv API, Semantic Scholar API, and user-defined RSS feeds.
- **FR-003**: System MUST support web scraping for user-defined URLs that are not RSS/API sources.
- **FR-003a**: System MUST accept a user-provided list of web resources/sites during `init` and via `sources add` — this is a primary input, not optional.
- **FR-003b**: System MUST auto-detect source type (RSS/Atom, API, generic web page) when a user provides a URL, and select the appropriate fetch adapter.
- **FR-003c**: System MUST support batch import of source URLs from a file (`--sources-file` flag on init, `sources import` command).
- **FR-003d**: System MUST provide a `sources test <url>` command that probes a URL, reports reachability, detected type, and sample extracted items — so users can validate before adding.
- **FR-004**: System MUST deduplicate publications across sources using DOI (primary) and title fuzzy matching (secondary).
- **FR-005**: System MUST score each publication for relevance using a two-pass approach: (a) keyword pre-filter, (b) LLM-based relevance scoring with configurable model.
- **FR-006**: System MUST generate an HTML email digest sorted by relevance score, including title, authors, abstract snippet, score, source, date, and link.
- **FR-007**: System MUST include per-item feedback links (thumbs up/down) in the email digest.
- **FR-008**: System MUST record feedback in a local SQLite database and incorporate it into future scoring prompts.
- **FR-009**: System MUST support `--dry-run` mode for all outbound operations (email, API calls).
- **FR-010**: System MUST log every pipeline run with structured output: sources checked, items fetched, items scored, items reported, errors encountered.
- **FR-011**: System MUST persist publication history in SQLite to avoid re-reporting previously seen publications.
- **FR-012**: System MUST support configurable relevance threshold (default: 5/10).
- **FR-013**: System MUST support include/exclude keyword filters as hard constraints.
- **FR-014**: System MUST gracefully degrade when individual sources or the LLM API are unavailable.
- **FR-015**: System MUST expose a CLI with commands: `init`, `scan`, `sources`, `feedback`, `history`, `stats`.
- **FR-016**: System MUST support a lightweight local HTTP server for processing feedback link clicks from emails.

### Non-Functional Requirements

- **NFR-001**: A full scan cycle SHOULD complete within 5 minutes for ≤500 publications across all sources.
- **NFR-002**: LLM API costs per scan SHOULD be bounded — pre-filter with keywords to limit LLM calls to ≤100 items per scan.
- **NFR-003**: All user data MUST remain local (no telemetry, no cloud sync beyond configured sources and email).
- **NFR-004**: The system MUST work on Windows 10+, macOS 12+, and Linux (Ubuntu 22.04+).
- **NFR-005**: Configuration MUST be human-readable and editable (YAML).

### Key Entities

- **UserProfile**: Domains, keywords, source list, email config, LLM config, scoring thresholds, include/exclude filters.
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
- User has access to an OpenAI-compatible LLM API endpoint (Azure OpenAI or OpenAI; API key required).
- User has an email account accessible via SMTP or Microsoft Graph API for sending digests.
- arXiv and Semantic Scholar APIs are publicly available and rate-limit-friendly for daily queries.
- Daily publication volume per user profile is <1000 items (pre-filter), <100 items (post-filter for LLM scoring).
- The feedback mechanism uses a lightweight local HTTP server; the user's email client must be able to open localhost URLs (alternative: CLI feedback command).
- Mobile support is out of scope for v1.
- Multi-user support is out of scope for v1 (single-user, single-profile).

---

## Open Questions

1. **Feedback server lifecycle**: Should the local feedback HTTP server run as a persistent background service, or start-on-demand when a feedback link is clicked? Trade-off: always-on is simpler for the user but consumes resources; on-demand adds latency.
2. **LLM prompt strategy**: Should the relevance scoring prompt include the full abstract or just title + keywords? Full abstract gives better accuracy but costs more tokens.
3. **Source discovery**: Should the system suggest new sources based on user domains (e.g., auto-discover RSS feeds for "AI accelerators"), or only use explicitly configured sources?
4. **Digest frequency**: Should the system support weekly digests in addition to daily? Or is daily the only cadence for v1?
5. **Rate limiting**: How should the system handle arXiv/Semantic Scholar rate limits? Backoff + retry, or cache and spread requests across the day?

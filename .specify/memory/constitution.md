# PubScout Constitution

## Core Principles

### I. Modular Pipeline Architecture
The system is a pipeline of discrete, independently testable stages: **Source → Fetch → Filter → Score → Report → Feedback**. Each stage has a clear contract (input/output schema). Stages communicate via structured data (JSON/dataclass), never by side effects. New sources, scorers, or delivery channels are added by implementing a stage interface — no modification of existing stages required.

### II. User Preferences as First-Class Data
All user-defined configuration — domains, keywords, source URLs, relevance criteria, feedback history — is stored in a structured, versionable profile. The system never hard-codes domain knowledge. All filtering and scoring decisions are traceable back to user preferences and feedback signals.

### III. Test-First Development (NON-NEGOTIABLE)
TDD is mandatory. Red-Green-Refactor cycle strictly enforced. Every pipeline stage must have unit tests with mock inputs/outputs. Integration tests cover the full pipeline from source fetch to report generation. Relevance scoring must have golden-set tests (known-relevant and known-irrelevant publications).

### IV. Graceful Degradation & Observability
If a source is unreachable, the pipeline continues with available sources and logs the failure. Every pipeline run produces a structured log: sources checked, items fetched, items filtered, items scored, report generated. Errors are never swallowed — they are logged with context and surfaced in the daily report summary.

### V. Privacy & Data Minimality
The system stores only publication metadata (title, authors, abstract, URL, date, source). Full-text content is never stored — only fetched transiently for scoring. User feedback (thumbs up/down) is stored locally. No user data leaves the local system except for outbound API calls to configured sources and the email delivery service.

### VI. Simplicity & Incremental Delivery
Start with the simplest viable implementation for each stage. Prefer standard libraries and well-maintained packages. Avoid premature optimization — the daily scan volume is expected to be <1000 items. Ship a working end-to-end pipeline before adding sophistication (e.g., embeddings, ML models).

## Technology Constraints

- **Language**: Python 3.11+
- **Package Management**: `uv` for dependency management
- **Configuration**: YAML for user profiles, JSON for internal data exchange
- **Scheduling**: System scheduler (cron / Windows Task Scheduler) — the app itself is a CLI that runs once per invocation
- **LLM Integration**: OpenAI-compatible API (Azure OpenAI or OpenAI) for relevance scoring; must support configurable model/endpoint
- **Email Delivery**: SMTP or Microsoft Graph API (configurable)
- **Storage**: SQLite for publication history, deduplication, and feedback tracking
- **No external services beyond**: configured source APIs, LLM API, email service

## Development Workflow

- All code changes require passing tests before merge
- Every new source adapter must include at least one integration test with recorded fixtures
- Relevance scoring changes must be validated against the golden-set test suite
- Configuration schema changes require migration scripts for existing user profiles
- CLI commands must support `--dry-run` for all destructive or outbound operations

## Governance

This constitution governs all development decisions for PubScout. Amendments require documentation of rationale and impact assessment. The pipeline stage contract interfaces are the most protected artifacts — changes require careful consideration of upstream/downstream impact.

**Version**: 1.0.0 | **Ratified**: 2026-03-26 | **Last Amended**: 2026-03-26

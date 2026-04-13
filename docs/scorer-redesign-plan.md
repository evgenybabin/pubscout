# PubScout Scorer Redesign Plan

> **Status:** Deferred — saved for future implementation  
> **Created:** 2026-04-06  
> **Current scoring:** GPT-4o-mini via OpenAI SDK (keyword fallback without API key)

---

## Problem Statement

The current scorer has three gaps:

1. **No usable free default.** Without an OpenAI API key, the keyword fallback (`matched_domains × 2.0`) yields scores of 2.0–4.0, all below the 5.0 threshold → zero results. New users get an empty report.
2. **Single provider lock-in.** `scorer.py` is hardcoded to the OpenAI SDK. The `provider` config field exists but is ignored.
3. **No way to guide scoring.** Users can only influence results via domain queries and thumbs up/down. There's no way to say *"I care about hardware-specific optimizations, not general GPU work."*

## Design Overview

Three interconnected features, implemented bottom-up:

```
┌──────────────────────────────────────────────────────────┐
│  LAYER 3: User Guidance                                  │
│  scoring_instructions in profile.yaml → injected into    │
│  LLM prompt context; ignored by keyword scorer           │
│  CLI: pubscout config instructions "..."                 │
├──────────────────────────────────────────────────────────┤
│  LAYER 2: Provider Abstraction                           │
│  LLMProvider Protocol → OpenAI, Azure, Anthropic, Ollama │
│  create_provider(LLMConfig) factory                      │
│  CLI: pubscout config provider <name>                    │
├──────────────────────────────────────────────────────────┤
│  LAYER 1: Enhanced Keyword Scorer (Free Default)         │
│  TF-IDF-like domain weighting, zero external deps        │
│  Works out of the box — no API key, no install           │
│  CLI: automatic when provider = "keyword" (default)      │
└──────────────────────────────────────────────────────────┘
```

---

## LAYER 1: Enhanced Keyword Scorer (Free Default)

**Goal:** Replace the broken `min(matched_domains × 2.0, 10.0)` heuristic with a scoring algorithm that produces useful rankings without any LLM.

### Algorithm: Weighted Domain-Signal Scoring

```
score = Σ (domain_match_score × domain_weight) + title_bonus + recency_bonus

Where:
  domain_match_score = base (2.0) + keyword_density_bonus (0–2.0) + field_bonus (0–1.0)
    - keyword_density_bonus: proportion of domain query terms found in abstract, scaled 0–2.0
    - field_bonus: +1.0 if query terms appear in TITLE (not just abstract)
  domain_weight = 1.0 for all domains (future: user-configurable)
  title_bonus: +0.5 if title contains exact multi-word phrases from domain queries
  recency_bonus: +0.5 if published within last 3 days (configurable)

Final score capped at 10.0, normalized to 1–10 scale.
```

**Why this works:** A paper matching 2 domains with high keyword density in the title scores ~7.0–8.0, above the 5.0 threshold. A paper barely matching 1 domain by a single abstract keyword scores ~2.5–3.0 and gets filtered.

**Config default change:**
```python
class LLMConfig(BaseModel):
    provider: str = "keyword"    # CHANGED from "openai" — free by default
    model: str = "gpt-4o-mini"   # only used when provider != "keyword"
```

**Files to change:**
- `core/scorer.py` — Add `_keyword_score()` method alongside `_llm_score()`
- `core/models.py` — Change default provider to `"keyword"`

---

## LAYER 2: Provider Abstraction

**Goal:** Let users switch between LLM providers without touching code.

### Architecture

```
core/providers/
  __init__.py              ← PROVIDER_REGISTRY + create_provider() factory
  base.py                  ← LLMProvider Protocol
  keyword_provider.py      ← Enhanced keyword scorer (Layer 1)
  openai_provider.py       ← OpenAI + Azure OpenAI (auto-detect via endpoint)
  anthropic_provider.py    ← Claude (optional dep: pip install anthropic)
  ollama_provider.py       ← Local models via OpenAI-compat API (free)
```

### Provider Protocol

```python
class LLMProvider(Protocol):
    def complete(self, prompt: str) -> str:
        """Send prompt, return raw text response."""
        ...

    @property
    def name(self) -> str:
        """Human-readable provider name for display."""
        ...

    @property
    def is_available(self) -> bool:
        """Whether this provider is configured and reachable."""
        ...
```

### Provider Registry & Factory

```python
PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "keyword":   KeywordProvider,      # always available, free
    "openai":    OpenAIProvider,       # needs OPENAI_API_KEY
    "azure":     AzureOpenAIProvider,  # needs endpoint + api_version + key
    "anthropic": AnthropicProvider,    # needs pip install anthropic + key
    "ollama":    OllamaProvider,       # needs ollama running locally
}

def create_provider(config: LLMConfig) -> LLMProvider:
    cls = PROVIDER_REGISTRY.get(config.provider)
    if cls is None:
        raise ValueError(f"Unknown provider: {config.provider}")
    return cls(config)
```

### Provider Comparison

| Provider | Cost | Requirement |
|----------|------|-------------|
| `keyword` | Free | Nothing (default) |
| `ollama` | Free | Ollama installed locally |
| `openai` | ~$0.01–0.03/scan | API key |
| `azure` | Paid | Endpoint + key |
| `anthropic` | Paid | `pip install anthropic` + key |

### Scorer Refactor

```python
class RelevanceScorer:
    def __init__(self, llm_config, scoring_config):
        self.provider = create_provider(llm_config)
        ...

    def _llm_score(self, pub, domains, ...):
        if isinstance(self.provider, KeywordProvider):
            return self.provider.score_publication(pub, domains)
        prompt = self._build_scoring_prompt(pub, domains, ...)
        content = self.provider.complete(prompt)
        return self._parse_llm_response(content)
```

### LLMConfig Additions

```python
class LLMConfig(BaseModel):
    provider: str = "keyword"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    endpoint: str | None = None
    api_version: str | None = None          # NEW — for Azure OpenAI
    scoring_instructions: str | None = None  # NEW — Layer 3
```

---

## LAYER 3: User Scoring Guidance

**Goal:** Let users provide free-form instructions that shape how the LLM evaluates relevance.

### How It Works

- User writes natural language guidance, stored in `profile.yaml` as `llm.scoring_instructions`
- Injected into the LLM prompt between "USER INTERESTS" and "PUBLICATION TO SCORE"
- Ignored when provider is `"keyword"` (keyword scorer doesn't use prompts)

### Example

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  scoring_instructions: |
    Focus on papers about hardware-specific optimizations for custom AI accelerators
    (like Maia), not general GPU work. Prioritize papers that include:
    - Actual performance numbers or benchmarks
    - Novel memory management or scheduling techniques
    - Disaggregated inference architectures
    De-prioritize survey papers and purely theoretical work.
```

### Prompt Injection Point

```python
if self.scoring_instructions:
    lines.append("")
    lines.append("ADDITIONAL SCORING GUIDANCE FROM USER:")
    lines.append(self.scoring_instructions)
```

### CLI

```
pubscout config instructions "Focus on hardware-specific optimizations..."
pubscout config instructions --edit    # opens in $EDITOR / notepad
pubscout config instructions --clear   # remove guidance
```

---

## CLI: Model Selection UI

### Interactive Wizard (`pubscout config setup-scoring`)

```
$ pubscout config setup-scoring

Step 1: Choose a scoring method

  ❯ keyword     Free — no API key needed (enhanced keyword matching)
    openai      Paid — GPT-4o-mini ($0.01/scan), GPT-4o ($0.10/scan)
    anthropic   Paid — Claude Sonnet, requires pip install anthropic
    ollama      Free — local models, requires Ollama installed
    azure       Paid — Azure OpenAI, requires endpoint + key

Step 2: Select model (only if not "keyword")
  ❯ gpt-4o-mini    Fast, cheap ($0.15/1M input)
    gpt-4o          More capable ($2.50/1M input)
    gpt-4-turbo     Strongest reasoning ($10/1M input)

Step 3: API key
  Enter API key (or set OPENAI_API_KEY env var): sk-...

Step 4: Scoring guidance (optional)
  Add custom instructions to guide relevance scoring? [y/N]: y
  (opens editor)

✓ Scoring configured: openai / gpt-4o-mini
```

### Quick Commands

```
pubscout config provider keyword           # switch to free keyword scorer
pubscout config provider openai            # switch to OpenAI
pubscout config model gpt-4o              # change model
pubscout config instructions "..."         # set guidance
pubscout config instructions --edit        # edit in $EDITOR
pubscout config instructions --clear       # remove guidance
pubscout config setup-scoring              # guided wizard
```

---

## Full Profile.yaml Example

```yaml
domains: [...]
sources: [...]
scan_range_days: 7
scoring:
  threshold: 5.0
  include_keywords: []
  exclude_keywords: []
llm:
  provider: keyword                        # keyword | openai | azure | anthropic | ollama
  model: gpt-4o-mini                       # ignored when provider=keyword
  api_key: null                            # env: OPENAI_API_KEY / ANTHROPIC_API_KEY
  endpoint: null                           # for azure/ollama
  api_version: null                        # for azure
  scoring_instructions: null               # free-form LLM guidance (Layer 3)
```

---

## Implementation Order

```
Phase A — Foundation (no behavior change yet)
  A1: LLMProvider Protocol (base.py)
  A2: Enhanced keyword scoring algorithm (keyword_provider.py)
  A3: Extract OpenAI into provider (openai_provider.py)

Phase B — More Providers (parallel)
  B1: Azure OpenAI provider (in openai_provider.py)
  B2: Anthropic provider (anthropic_provider.py)
  B3: Ollama provider (ollama_provider.py)
  B4: Provider factory + registry (__init__.py)

Phase C — Wiring
  C1: Update LLMConfig (add api_version, scoring_instructions, default=keyword)
  C2: Refactor scorer to use providers
  C3: Inject scoring_instructions into prompt

Phase D — CLI
  D1: config provider <name> command
  D2: config instructions (set/edit/clear)
  D3: config setup-scoring wizard
  D4: Update config show
  D5: Update init wizard

Phase E — Docs & Tests
  E1: Unit tests for each provider + keyword scorer
  E2: Integration test: full scan with keyword scorer
  E3: Update spec to v4
  E4: Update README with provider docs
```

### Dependency Graph

```
A1 ──→ A2 ──┐
  │         │
  └──→ A3 ──┼──→ B1
       │    │      └──→ B4 ──→ C2 ──→ C3 ──→ D2 ──→ D3 ──→ D5
       │    │              │         │
       └──→ B3 ──→ B4     └──→ C1 ──┘  D1 ──→ D4
                                        │
  A1 ──→ B2 ──→ B4                      └──→ D3

Phase E (E1–E4) depends on C2 completion.
```

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Keyword scorer ranking quality | Users get poor recommendations without LLM | Tune algorithm against known-good papers; keep threshold at 5.0 which filters ~60% |
| Scoring instructions prompt injection | User text injected into LLM prompt | Low risk — user controls their own profile, not untrusted input |
| Anthropic SDK not installed | ImportError at runtime | Guard import, raise `"pip install pubscout[anthropic]"` message |
| Ollama not running | Connection refused | Catch error, suggest `ollama serve` or fall back to keyword |
| Azure auth complexity | AAD tokens, managed identity | Start with API key only; AAD deferred |

---

## Current Scoring Architecture (for reference)

**File:** `src/pubscout/core/scorer.py` — `RelevanceScorer` class

### 4-Pass Pipeline

1. **Keyword pre-filter** (`_keyword_prefilter`): Check if title+abstract contains any domain query terms. Skip LLM call entirely if no keyword matches.
2. **LLM scoring** (`_llm_score`): Build prompt with domain context + feedback examples + pub metadata → OpenAI `chat.completions.create()` with `temperature=0.0` → parse JSON `{"score": float, "reason": str}`.
3. **Hard keyword filters** (`_apply_hard_filters`): Boost score by +2.0 if include_keywords match; set to 0.0 if exclude_keywords match.
4. **Threshold filter**: Keep papers with `score >= threshold` (default 5.0).

### Keyword Fallback (broken)

Without an API key: `min(len(matched_domains) * 2.0, 10.0)` — most papers match 1 domain → score 2.0, below threshold → zero results.

### Feedback Integration

Up to 20 positive + 20 negative example titles injected into LLM prompt as "Previously rated publications" context.

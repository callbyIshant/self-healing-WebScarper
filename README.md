# Self-Healing Web Scraping Pipeline

A production-grade data extraction pipeline that automatically detects site layout drift and repairs broken selectors using AI, within strict safety guardrails.

## Architecture

The system is organized into **9 layers**, each with distinct responsibilities:

```
┌─────────────────────────────────────────────────────────┐
│                    Telemetry Layer (L9)                   │
│              (observes all layers below)                  │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  [Request] ──► L1: Compliance Gate                       │
│            ──► L2: Rate Limiter (Token Bucket)           │
│            ──► L3: Data Plane (Deterministic Extraction)  │
│                  │                                        │
│            ┌─────┤ On Success: Emit + Update LKG         │
│            │     │                                        │
│            │     └─ On Failure:                           │
│            │         ──► L4: Validation (Type/Biz/Stats) │
│            │         ──► L5: Circuit Breakers             │
│            │              (Spatial + Temporal)            │
│            │         ──► L6: Self-Healing Agent (LLM)    │
│            │         ──► L7: Cross-Validation            │
│            │         ──► L8: Confidence Gate / Quarantine │
│            │                                              │
│            └──► [Response]                                │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

## Key Features

- **Semantic Locators** — Prioritizes ARIA roles and accessibility-tree locators over brittle CSS selectors
- **Self-Healing** — AI agent (Google Gemini) repairs broken selectors with structured, validated output
- **Fail-Closed Design** — Missing signals always default to the safest behavior
- **Circuit Breakers** — Spatial (blast-radius) and temporal (thrash) breakers prevent runaway healing
- **Cross-Validation** — Repairs tested against holdout pages to reject overfit selectors
- **Prompt Injection Defense** — Multi-layer sanitization of DOM content before LLM exposure
- **SSRF Protection** — URL validation with IP blocklists, protocol whitelisting, redirect interception
- **PII Redaction** — Automated scrubbing before storage
- **Compliance-First** — robots.txt (RFC 9309), legal manifests, rate limiting

## Quick Start

### Prerequisites
- Python 3.11+
- Redis (optional — falls back to in-memory rate limiting)
- Google Gemini API key (for self-healing)

### Installation

```bash
# Clone and install
git clone <repo-url>
cd self-healing-web-scraper
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium

# Copy environment config
cp .env.example .env
# Edit .env with your GEMINI_API_KEY
```

### Usage

```bash
# Scrape a single page
scraper scrape https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html \
  --domain books.toscrape.com

# List configured domains
scraper list-domains

# Reset a thrashed field breaker
scraper reset-breaker books.toscrape.com price --reset-by "ops-engineer"

# View quarantine queue
scraper quarantine-list --domain books.toscrape.com

# Start Prometheus metrics server
scraper metrics --port 9090
```

### Docker

```bash
cd docker
docker-compose up
```

## Configuration

All configuration lives in `config/` and is version-controlled:

| File | Purpose | Owner |
|------|---------|-------|
| `scraping_postures.yaml` | Legal compliance posture per domain | Legal / Compliance |
| `business_rules.yaml` | Field validation rules | Data Steward |
| `volatility_profiles.yaml` | Statistical anomaly thresholds | Data Steward |
| `domains/*.yaml` | Per-domain extraction schema | ML/Ops Engineer |

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src/scraper --cov-report=html

# Run security tests only
pytest tests/test_security.py -v

# Run integration tests (requires Redis)
pytest tests/test_pipeline_integration.py -v -m integration
```

## Scripts

```bash
# Backfill quarantined records after manual fix
python scripts/backfill_replay.py --db data/scraper.db

# Calibrate confidence threshold from historical repairs
python scripts/calibrate_threshold.py --db data/scraper.db
```

## Technology Stack

| Concern | Technology |
|---------|-----------|
| Browser Automation | Playwright (≥1.49) |
| Data Validation | Pydantic v2 |
| LLM Integration | Google Gemini (google-genai) |
| Document Store | SQLite (WAL mode) |
| Ephemeral Cache | Redis |
| Telemetry | structlog + prometheus-client |
| robots.txt | protego (RFC 9309) |

## License

MIT

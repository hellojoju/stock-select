# stock-select

## Project Context

A-share stock selection system with self-evolving strategy genes. Daily automated pipeline: sync data → candidate screening → simulation → review → evolution.

## Stack

- **Python 3.11+** backend, SQLite (WAL mode, FTS5)
- **React + Vite + TypeScript** frontend (`web/`)
- **APScheduler** for daily trading workflow
- **NetworkX** for knowledge graph

## Key Directories

- `src/stock_select/` — core modules (pipeline, strategies, evolution, review, API)
- `tests/` — 450+ tests, all passing
- `web/` — frontend application
- `var/` — SQLite database and runtime data

## Running

```bash
# Demo mode (no API keys needed)
uv run stock-select serve --demo

# Live mode
cp .env.example .env  # edit with API keys
uv run stock-select serve
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `stock-select serve` | Start web server + scheduler |
| `stock-select serve --demo` | Demo mode with seeded data |
| `stock-select pipeline` | Run full daily pipeline once |
| `stock-select pipeline --demo` | Pipeline in demo mode |
| `stock-select sync` | Sync data only |
| `stock-select status` | Show system status |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key (for LLM review) |
| `LLM_PROVIDER` | LLM provider (`deepseek`, `anthropic`, etc.) |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | DeepSeek API base URL (optional) |
| `MODE` | `demo` or `live` |

## Testing

```bash
pytest tests/ -q
```

450+ tests covering integration, unit, scheduler, data ingestion, planner, and E2E.

## Architecture Notes

- Backend unified on FastAPI (`api.py`); `server.py` retained for backward compatibility
- Pipeline orchestrated via `run_phase()` in `agent_runtime.py`
- Strategy evolution: challenger → observing → promotion/rollback lifecycle
- Deterministic review uses fixed rules; LLM review uses Claude/DeepSeek

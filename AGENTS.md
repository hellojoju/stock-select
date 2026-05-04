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
uv run stock-select serve --mode demo --port 18425

# Live mode
cp .env.example .env  # edit with API keys
uv run stock-select serve --mode live
```

Backend: http://localhost:18425
Frontend: http://localhost:5173

## CLI Commands

| Command | Description |
|---------|-------------|
| `uv run stock-select serve --mode demo` | Start web server + scheduler |
| `uv run stock-select pipeline --date YYYY-MM-DD` | Run full daily pipeline once |
| `uv run stock-select run-daily --date YYYY-MM-DD` | Picks + simulate (no data sync) |
| `uv run stock-select run-phase <phase> --date YYYY-MM-DD` | Run a named pipeline phase |
| `uv run stock-select init-db` | Initialize database schema |
| `uv run stock-select seed-demo` | Seed demo data |
| `uv run stock-select performance` | Show strategy performance |
| `uv run stock-select memory-search --q <keyword>` | Search FTS5 memory |

All commands support `--mode demo` or `--mode live`.

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

- Backend defaults to stdlib HTTPServer (`server.py`); auto-upgrades to FastAPI if uvicorn is installed
- Pipeline orchestrated via `run_phase()` in `agent_runtime.py`
- Strategy evolution: challenger → observing → promotion/rollback lifecycle
- Deterministic review uses fixed rules; LLM review uses Claude/DeepSeek
- Scheduler jobs run Mon-Fri 7:00-16:00 for trading workflow, Sat 10:00 for gene evolution

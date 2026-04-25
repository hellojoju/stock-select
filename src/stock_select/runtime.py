from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


VALID_RUNTIME_MODES = {"demo", "live"}
DEMO_DB_PATH = Path("var/stock_select_demo.db")
LIVE_DB_PATH = Path("var/stock_select_live.db")
LEGACY_DB_PATH = Path("var/stock_select.db")


@dataclass(frozen=True)
class RuntimeContext:
    mode: str
    db_path: Path
    database_role: str

    @property
    def is_demo_data(self) -> bool:
        return self.mode == "demo"

    def as_payload(self) -> dict[str, object]:
        return {
            "runtime_mode": self.mode,
            "database_role": self.database_role,
            "is_demo_data": self.is_demo_data,
        }


def resolve_runtime(mode: str = "demo", db_path: str | Path | None = None) -> RuntimeContext:
    if mode not in VALID_RUNTIME_MODES:
        raise ValueError(f"Unknown runtime mode: {mode}")
    if db_path:
        path = Path(db_path)
        if path == LIVE_DB_PATH:
            role = "live"
        elif path == DEMO_DB_PATH:
            role = "demo"
        elif path == LEGACY_DB_PATH:
            role = "legacy"
        else:
            role = "custom"
    elif mode == "live":
        path = LIVE_DB_PATH
        role = "live"
    else:
        path = DEMO_DB_PATH
        role = "demo"
    return RuntimeContext(mode=mode, db_path=path, database_role=role)

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 策略基因必填参数及类型
GENE_REQUIRED_PARAMS: dict[str, type] = {
    "max_picks": int,
    "min_score": float,
    "position_pct": float,
    "take_profit_pct": float,
    "stop_loss_pct": float,
    "time_exit_days": int,
}

GENE_OPTIONAL_PARAMS: dict[str, type] = {
    "lookback_days": int,
    "momentum_weight": float,
    "volume_weight": float,
    "volatility_weight": float,
    "volatility_penalty": float,
    "technical_component_weight": float,
    "fundamental_component_weight": float,
    "event_component_weight": float,
    "sector_component_weight": float,
    "risk_component_weight": float,
    "max_per_industry": int,
    "min_avg_amount": int,
}


@dataclass(frozen=True)
class GeneHealthResult:
    gene_id: str
    name: str
    is_valid: bool
    missing_required: list[str]
    type_errors: list[str]


def check_all_genes(conn: sqlite3.Connection) -> list[GeneHealthResult]:
    """Scan all active strategy genes and validate their params_json."""
    results: list[GeneHealthResult] = []
    rows = conn.execute(
        "SELECT gene_id, name, params_json FROM strategy_genes WHERE status = 'active'"
    ).fetchall()

    for row in rows:
        gene_id = row["gene_id"]
        name = row["name"]
        try:
            params = json.loads(row["params_json"])
        except (json.JSONDecodeError, TypeError) as e:
            results.append(
                GeneHealthResult(
                    gene_id=gene_id,
                    name=name,
                    is_valid=False,
                    missing_required=[],
                    type_errors=[f"params_json is not valid JSON: {e}"],
                )
            )
            continue

        missing = [k for k in GENE_REQUIRED_PARAMS if k not in params]
        type_errors: list[str] = []
        for key, expected_type in {**GENE_REQUIRED_PARAMS, **GENE_OPTIONAL_PARAMS}.items():
            if key in params and not isinstance(params[key], (expected_type, int)):
                # int is acceptable for float fields
                if expected_type is float and isinstance(params[key], int):
                    continue
                type_errors.append(
                    f"{key} should be {expected_type.__name__}, got {type(params[key]).__name__}"
                )

        results.append(
            GeneHealthResult(
                gene_id=gene_id,
                name=name,
                is_valid=len(missing) == 0 and len(type_errors) == 0,
                missing_required=missing,
                type_errors=type_errors,
            )
        )

    return results


def startup_health_check(conn: sqlite3.Connection) -> dict[str, Any]:
    """Run full startup health check and return summary."""
    gene_results = check_all_genes(conn)
    invalid_genes = [r for r in gene_results if not r.is_valid]

    if invalid_genes:
        for r in invalid_genes:
            logger.error(
                "Gene %s (%s) has invalid params: missing=%s, type_errors=%s",
                r.gene_id,
                r.name,
                r.missing_required,
                r.type_errors,
            )

    # Mark invalid genes as inactive to prevent crashes
    for r in invalid_genes:
        conn.execute(
            "UPDATE strategy_genes SET status = 'inactive' WHERE gene_id = ?",
            (r.gene_id,),
        )
    if invalid_genes:
        conn.commit()
        logger.warning("Marked %d invalid genes as inactive", len(invalid_genes))

    return {
        "genes_checked": len(gene_results),
        "genes_valid": len(gene_results) - len(invalid_genes),
        "genes_invalid": len(invalid_genes),
        "invalid_details": [
            {
                "gene_id": r.gene_id,
                "name": r.name,
                "missing": r.missing_required,
                "type_errors": r.type_errors,
            }
            for r in invalid_genes
        ],
        "overall_ok": len(invalid_genes) == 0,
    }


from typing import Any

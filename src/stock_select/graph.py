from __future__ import annotations

import sqlite3
from typing import Any

import networkx as nx

from . import repository


def build_graph(conn: sqlite3.Connection) -> nx.DiGraph:
    graph = nx.DiGraph()
    for row in conn.execute("SELECT * FROM graph_nodes"):
        graph.add_node(row["node_id"], type=row["node_type"], label=row["label"], **repository.loads(row["props_json"], {}))
    for row in conn.execute("SELECT * FROM graph_edges"):
        graph.add_edge(
            row["source_node_id"],
            row["target_node_id"],
            edge_id=row["edge_id"],
            type=row["edge_type"],
            confidence=row["confidence"],
            **repository.loads(row["props_json"], {}),
        )
    return graph


def sync_decision_graph(conn: sqlite3.Connection, trading_date: str) -> dict[str, int]:
    decisions = conn.execute(
        """
        SELECT p.*, o.return_pct, o.outcome_id
        FROM pick_decisions p
        LEFT JOIN outcomes o ON o.decision_id = p.decision_id
        WHERE p.trading_date = ?
        """,
        (trading_date,),
    ).fetchall()
    nodes = 0
    edges = 0
    market_node = upsert_node(
        conn,
        f"market:{trading_date}",
        "MarketDay",
        trading_date,
        {"trading_date": trading_date},
    )
    nodes += market_node
    for decision in decisions:
        gene_id = f"gene:{decision['strategy_gene_id']}"
        stock_id = f"stock:{decision['stock_code']}"
        pick_id = f"pick:{decision['decision_id']}"
        nodes += upsert_node(conn, gene_id, "StrategyGene", decision["strategy_gene_id"], {})
        nodes += upsert_node(conn, stock_id, "Stock", decision["stock_code"], {})
        nodes += upsert_node(
            conn,
            pick_id,
            "PickDecision",
            decision["decision_id"],
            {"score": float(decision["score"]), "confidence": float(decision["confidence"])},
        )
        edges += upsert_edge(conn, gene_id, pick_id, "EXECUTED", "EXTRACTED", {})
        edges += upsert_edge(conn, pick_id, market_node_id(trading_date), "BASED_ON", "EXTRACTED", {})
        edges += upsert_edge(conn, pick_id, stock_id, "SELECTED", "EXTRACTED", {})
        if decision["outcome_id"]:
            outcome_id = f"outcome:{decision['outcome_id']}"
            nodes += upsert_node(conn, outcome_id, "Outcome", decision["outcome_id"], {"return_pct": float(decision["return_pct"])})
            edges += upsert_edge(conn, pick_id, outcome_id, "PRODUCED", "EXTRACTED", {})
    conn.commit()
    return {"nodes": nodes, "edges": edges}


def query_graph(conn: sqlite3.Connection, node_type: str | None = None, limit: int = 100) -> dict[str, Any]:
    params: tuple[Any, ...] = ()
    where = ""
    if node_type:
        where = "WHERE node_type = ?"
        params = (node_type,)
    nodes = [dict(row) for row in conn.execute(f"SELECT * FROM graph_nodes {where} LIMIT ?", (*params, limit))]
    edges = [dict(row) for row in conn.execute("SELECT * FROM graph_edges LIMIT ?", (limit,))]
    return {"nodes": nodes, "edges": edges}


def upsert_node(conn: sqlite3.Connection, node_id: str, node_type: str, label: str, props: dict[str, Any]) -> int:
    conn.execute(
        """
        INSERT INTO graph_nodes(node_id, node_type, label, props_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
          node_type = excluded.node_type,
          label = excluded.label,
          props_json = excluded.props_json
        """,
        (node_id, node_type, label, repository.dumps(props)),
    )
    return 1


def upsert_edge(
    conn: sqlite3.Connection,
    source: str,
    target: str,
    edge_type: str,
    confidence: str,
    props: dict[str, Any],
) -> int:
    edge_id = f"edge:{source}:{edge_type}:{target}"
    conn.execute(
        """
        INSERT INTO graph_edges(edge_id, source_node_id, target_node_id, edge_type, confidence, props_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(edge_id) DO UPDATE SET
          confidence = excluded.confidence,
          props_json = excluded.props_json
        """,
        (edge_id, source, target, edge_type, confidence, repository.dumps(props)),
    )
    return 1


def market_node_id(trading_date: str) -> str:
    return f"market:{trading_date}"


"""Knowledge graph operations with Graphify-style confidence and community detection."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

import networkx as nx

from . import repository

# Confidence levels matching Graphify semantics
CONFIDENCE_EXTRACTED = "EXTRACTED"
CONFIDENCE_INFERRED = "INFERRED"
CONFIDENCE_AMBIGUOUS = "AMBIGUOUS"


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
        edges += upsert_edge(conn, gene_id, pick_id, "EXECUTED", CONFIDENCE_EXTRACTED, {})
        edges += upsert_edge(conn, pick_id, market_node_id(trading_date), "BASED_ON", CONFIDENCE_EXTRACTED, {})
        edges += upsert_edge(conn, pick_id, stock_id, "SELECTED", CONFIDENCE_EXTRACTED, {})
        if decision["outcome_id"]:
            outcome_id = f"outcome:{decision['outcome_id']}"
            nodes += upsert_node(conn, outcome_id, "Outcome", decision["outcome_id"], {"return_pct": float(decision["return_pct"])})
            edges += upsert_edge(conn, pick_id, outcome_id, "PRODUCED", CONFIDENCE_EXTRACTED, {})
    conn.commit()
    return {"nodes": nodes, "edges": edges}


def sync_review_graph(conn: sqlite3.Connection, trading_date: str) -> dict[str, int]:
    """Sync ReviewEvidence, ReviewError, and OptimizationSignal nodes to the graph.

    S4.1-S4.3: Creates graph nodes for review artifacts with semantic edges
    connecting them to decisions, stocks, and strategy genes.
    """
    nodes = 0
    edges = 0

    # ReviewEvidence -> supports/contradicts decision
    evidence_rows = conn.execute(
        """
        SELECT e.*, dr.decision_id AS decision_id, d.stock_code, d.strategy_gene_id
        FROM review_evidence e
        JOIN decision_reviews dr ON dr.review_id = e.review_id
        JOIN pick_decisions d ON d.decision_id = dr.decision_id
        WHERE e.trading_date = ?
        """,
        (trading_date,),
    ).fetchall()
    for ev in evidence_rows:
        ev_node_id = f"evidence:{ev['evidence_id']}"
        pick_id = f"pick:{ev['decision_id']}"
        stock_id = f"stock:{ev['stock_code']}"
        nodes += upsert_node(conn, pick_id, "PickDecision", ev["decision_id"], {})
        nodes += upsert_node(conn, stock_id, "Stock", ev["stock_code"], {})
        nodes += upsert_node(conn, ev_node_id, "ReviewEvidence", ev["evidence_id"], {
            "source_type": ev["source_type"],
            "source_id": ev["source_id"],
            "visibility": ev["visibility"],
            "confidence": ev["confidence"],
            "payload_json": ev["payload_json"],
        })
        edges += upsert_edge(conn, ev_node_id, pick_id, "SUPPORTS_DECISION",
                            ev["confidence"], {"evidence_text": ev["payload_json"]})
        edges += upsert_edge(conn, ev_node_id, stock_id, "ABOUT_STOCK",
                            CONFIDENCE_EXTRACTED, {})

    # ReviewError -> generated from review
    error_rows = conn.execute(
        """
        SELECT e.*, d.stock_code, d.strategy_gene_id, d.decision_id as pick_decision_id
        FROM review_errors e
        JOIN decision_reviews dr ON dr.review_id = e.review_id
        JOIN pick_decisions d ON d.decision_id = dr.decision_id
        WHERE dr.trading_date = ?
        """,
        (trading_date,),
    ).fetchall()
    for err in error_rows:
        err_node_id = f"error:{err['error_id']}"
        review_id_node = f"review:{err['review_id']}"
        nodes += upsert_node(conn, review_id_node, "DecisionReview", err["review_id"], {})
        nodes += upsert_node(conn, err_node_id, "ReviewError", err["error_id"], {
            "error_type": err["error_type"],
            "severity": err["severity"],
            "confidence": err["confidence"],
            "review_scope": err["review_scope"],
        })
        edges += upsert_edge(conn, review_id_node, err_node_id, "GENERATED_ERROR",
                            CONFIDENCE_INFERRED, {})

    # OptimizationSignal -> generated from review
    signal_rows = conn.execute(
        """
        SELECT s.*, d.strategy_gene_id
        FROM optimization_signals s
        JOIN decision_reviews dr ON dr.review_id = s.source_id
        JOIN pick_decisions d ON d.decision_id = dr.decision_id
        WHERE s.created_at >= date(?)
        """,
        (trading_date,),
    ).fetchall()
    for sig in signal_rows:
        sig_node_id = f"signal:{sig['signal_id']}"
        review_id_node = f"review:{sig['source_id']}"
        target_gene_id = sig["target_gene_id"]
        gene_id_node = f"gene:{target_gene_id}" if target_gene_id else ""
        nodes += upsert_node(conn, review_id_node, "DecisionReview", sig["source_id"], {})
        if target_gene_id:
            nodes += upsert_node(conn, gene_id_node, "StrategyGene", target_gene_id, {})
        nodes += upsert_node(conn, sig_node_id, "OptimizationSignal", sig["signal_id"], {
            "signal_type": sig["signal_type"],
            "direction": sig["direction"],
            "strength": sig["strength"],
            "status": sig["status"],
            "param_name": sig["param_name"],
        })
        edges += upsert_edge(conn, review_id_node, sig_node_id, "GENERATED_SIGNAL",
                            CONFIDENCE_INFERRED, {})
        if gene_id_node:
            edges += upsert_edge(conn, sig_node_id, gene_id_node, "TARGETS_GENE",
                                CONFIDENCE_INFERRED, {})

    # EvolutionEvent nodes with edges to signals, reviews, and genes
    evolution_rows = conn.execute(
        """
        SELECT * FROM strategy_evolution_events
        WHERE period_start <= ? AND period_end >= ?
        """,
        (trading_date, trading_date),
    ).fetchall()
    for ev_event in evolution_rows:
        event_node_id = f"evolution:{ev_event['event_id']}"
        parent_gene = f"gene:{ev_event['parent_gene_id']}"
        nodes += upsert_node(conn, parent_gene, "StrategyGene", ev_event["parent_gene_id"], {})
        nodes += upsert_node(conn, event_node_id, "EvolutionEvent", ev_event["event_id"], {
            "event_type": ev_event["event_type"],
            "status": ev_event["status"],
            "rationale_json": ev_event["rationale_json"],
            "period_start": ev_event["period_start"],
            "period_end": ev_event["period_end"],
        })
        edges += upsert_edge(conn, parent_gene, event_node_id, "EVOLVED_TO",
                            CONFIDENCE_EXTRACTED, {})
        child_gene_id = ev_event["child_gene_id"]
        if child_gene_id:
            child_gene = f"gene:{child_gene_id}"
            nodes += upsert_node(conn, child_gene, "StrategyGene", child_gene_id, {})
            edges += upsert_edge(conn, event_node_id, child_gene, "PRODUCED",
                                CONFIDENCE_EXTRACTED, {})

        # S6.6: Link consumed signals to evolution event
        rationale = json.loads(ev_event["rationale_json"] or "{}")
        consumed_signal_ids = _extract_signal_ids_from_rationale(rationale)
        for sig_id in consumed_signal_ids:
            sig_node_id = f"signal:{sig_id}"
            edges += upsert_edge(conn, event_node_id, sig_node_id, "CONSUMED_SIGNAL",
                                CONFIDENCE_EXTRACTED, {"event_type": ev_event["event_type"]})

    conn.commit()
    return {"nodes": nodes, "edges": edges}


def sync_document_graph(
    conn: sqlite3.Connection,
    document_id: str,
    source: str,
    source_type: str,
    title: str,
    stock_codes: list[str],
    event_type: str | None = None,
    confidence: str = CONFIDENCE_EXTRACTED,
    as_of_date: str | None = None,
) -> dict[str, int]:
    """Create graph nodes/edges for a document and its linked stocks."""
    nodes = 0
    edges = 0

    # Document node
    doc_node_id = f"doc:{document_id}"
    doc_props = {
        "source": source,
        "source_type": source_type,
        "title": title,
        "as_of_date": as_of_date,
    }
    node_type = "Announcement" if "official" in source_type else "NewsArticle"
    nodes += upsert_node(conn, doc_node_id, node_type, title[:80], doc_props)

    # Link to stocks
    for code in stock_codes:
        stock_id = f"stock:{code}"
        nodes += upsert_node(conn, stock_id, "Stock", code, {})
        edge_props = {"event_type": event_type} if event_type else {}
        edges += upsert_edge(
            conn, doc_node_id, stock_id, "MENTIONS", confidence, edge_props
        )

    return {"nodes": nodes, "edges": edges}


def detect_communities(
    conn: sqlite3.Connection,
    trading_date: str | None = None,
) -> list[dict[str, Any]]:
    """Run Louvain community detection on the graph."""
    graph = build_graph(conn)
    if graph.number_of_nodes() < 2:
        return []

    try:
        import community as community_lib
        partition = community_lib.best_partition(graph, resolution=1.0)
    except ImportError:
        # Fallback: use connected components
        partition = {}
        for i, component in enumerate(nx.connected_components(graph.to_undirected())):
            for node in component:
                partition[node] = i

    communities: dict[int, list[str]] = {}
    for node, comm_id in partition.items():
        communities.setdefault(comm_id, []).append(node)

    results: list[dict[str, Any]] = []
    for comm_id, node_ids in sorted(communities.items(), key=lambda x: -len(x[1])):
        if len(node_ids) < 2:
            continue
        subgraph = graph.subgraph(node_ids)
        cohesion = nx.density(subgraph)

        # Extract top stocks and events
        top_stocks = [n for n in node_ids if n.startswith("stock:")]
        top_events = [n for n in node_ids if n.startswith(("doc:", "event:"))]

        community_id = f"comm_{trading_date or 'all'}_{comm_id}"
        label = f"社区 {comm_id} ({len(node_ids)} 节点)"

        results.append({
            "community_id": community_id,
            "trading_date": trading_date,
            "label": label,
            "summary": f"{len(node_ids)} 节点, {subgraph.number_of_edges()} 边",
            "node_ids": node_ids[:50],
            "cohesion_score": round(cohesion, 4),
            "top_stocks": [s.replace("stock:", "") for s in top_stocks[:10]],
            "top_events": top_events[:10],
        })

    return results


def store_communities(
    conn: sqlite3.Connection,
    communities: list[dict[str, Any]],
) -> int:
    """Store community detection results into graph_communities table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_communities (
          community_id TEXT PRIMARY KEY,
          trading_date TEXT,
          label TEXT NOT NULL,
          summary TEXT,
          node_ids_json TEXT NOT NULL,
          cohesion_score REAL NOT NULL DEFAULT 0,
          top_stocks_json TEXT NOT NULL DEFAULT '[]',
          top_events_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    stored = 0
    for c in communities:
        conn.execute(
            """
            INSERT OR REPLACE INTO graph_communities(
              community_id, trading_date, label, summary,
              node_ids_json, cohesion_score, top_stocks_json, top_events_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c["community_id"],
                c.get("trading_date"),
                c["label"],
                c.get("summary"),
                json.dumps(c.get("node_ids", []), ensure_ascii=False),
                c.get("cohesion_score", 0),
                json.dumps(c.get("top_stocks", []), ensure_ascii=False),
                json.dumps(c.get("top_events", []), ensure_ascii=False),
            ),
        )
        stored += 1
    conn.commit()
    return stored


def query_graph(
    conn: sqlite3.Connection,
    node_type: str | None = None,
    limit: int = 100,
    stock_code: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    where = ""
    if node_type:
        where = "WHERE node_type = ?"
        params.append(node_type)
    nodes = [dict(row) for row in conn.execute(f"SELECT * FROM graph_nodes {where} LIMIT ?", (*params, limit))]

    edges = [dict(row) for row in conn.execute("SELECT * FROM graph_edges LIMIT ?", (limit,))]

    if stock_code:
        # Get document-related edges for this stock
        doc_edges = conn.execute(
            """
            SELECT e.*, dsl.document_id
            FROM graph_edges e
            JOIN document_stock_links dsl ON e.source_node_id = 'doc:' || dsl.document_id
                                          OR e.target_node_id = 'doc:' || dsl.document_id
            WHERE dsl.stock_code = ?
            LIMIT ?
            """,
            (stock_code, limit),
        ).fetchall()
        edges.extend(dict(e) for e in doc_edges)

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
    confidence: str = CONFIDENCE_EXTRACTED,
    props: dict[str, Any] | None = None,
    source_document_id: str | None = None,
    evidence_text: str | None = None,
    as_of_date: str | None = None,
) -> int:
    edge_id = f"edge:{source}:{edge_type}:{target}"
    props = props or {}
    if source_document_id:
        props["source_document_id"] = source_document_id
    if evidence_text:
        props["evidence_text"] = evidence_text
    if as_of_date:
        props["as_of_date"] = as_of_date

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


def export_graphify_json(conn: sqlite3.Connection, output_path: str) -> str:
    """Export the graph in Graphify-compatible JSON format."""
    graph = build_graph(conn)

    nodes_out = []
    for nid, data in graph.nodes(data=True):
        nodes_out.append({
            "id": nid,
            "label": data.get("label", nid),
            "type": data.get("type", "unknown"),
            "props": {k: v for k, v in data.items() if k not in ("label", "type")},
        })

    edges_out = []
    for src, tgt, data in graph.edges(data=True):
        confidence = data.get("confidence", "INFERRED")
        edge = {
            "source": src,
            "target": tgt,
            "type": data.get("type", "unknown"),
            "confidence": confidence,
            "confidence_score": 0.9 if confidence == "EXTRACTED" else (0.6 if confidence == "INFERRED" else 0.4),
            "props": {k: v for k, v in data.items() if k not in ("type", "confidence", "edge_id")},
        }
        edges_out.append(edge)

    # Communities
    communities = detect_communities(conn)

    payload = {
        "version": "1.0",
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "stats": {
            "nodes": len(nodes_out),
            "edges": len(edges_out),
            "communities": len(communities),
        },
        "nodes": nodes_out,
        "edges": edges_out,
        "communities": communities,
    }

    import pathlib
    path = pathlib.Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _extract_signal_ids_from_rationale(rationale: dict[str, Any]) -> list[str]:
    """S6.6: Extract consumed signal IDs from evolution event rationale."""
    signal_ids: list[str] = []
    review_signal = rationale.get("review_signal", {})
    aggregated = review_signal.get("aggregated_signals", [])
    for item in aggregated:
        for sid in item.get("signal_ids", []):
            if sid not in signal_ids:
                signal_ids.append(sid)
    return signal_ids

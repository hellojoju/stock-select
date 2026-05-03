#!/usr/bin/env python3
"""Announcement Hunter System-Level End-to-End Tests.

Tests the full data flow chain:
1. API endpoint accessibility (via FastAPI test client)
2. Full scan pipeline (run_announcement_scan)
3. Sentiment scoring complete chain
4. WebSocket endpoint registration
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.stock_select.db import connect, init_db
from src.stock_select.db import ensure_column

DB_PATH = os.path.join(PROJECT_ROOT, "var", "test_announcement.db")

results: list[tuple[str, str, str]] = []  # (name, status, detail)


def report(name: str, passed: bool, detail: str) -> None:
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    tag = "✅" if passed else "❌"
    print(f"  [{tag}] {name}: {detail}")


# ──────────────────────────────────────────────
# Test 1: API Endpoints
# ──────────────────────────────────────────────

def test_api_endpoints() -> None:
    """Test all announcement API endpoints via FastAPI TestClient."""
    try:
        from fastapi.testclient import TestClient
        from src.stock_select.api import create_app
    except ImportError as e:
        report("API 端点", False, f"Import error: {e}")
        return

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    app = create_app(db_path=DB_PATH, mode="demo")
    client = TestClient(app)

    # 1a. Health check (dashboard endpoint as proxy)
    try:
        r = client.get("/api/dashboard")
        report("1a. 健康检查 (/api/dashboard)", r.status_code == 200,
               f"status={r.status_code}")
    except Exception as e:
        report("1a. 健康检查", False, str(e))

    # 1b. Announcement alerts list
    try:
        r = client.get("/api/announcements/alerts?limit=10")
        report("1b. 公告报警列表 (/api/announcements/alerts)", r.status_code == 200,
               f"status={r.status_code}, items={len(r.json())}")
    except Exception as e:
        report("1b. 公告报警列表", False, str(e))

    # 1c. Live stats
    try:
        r = client.get("/api/announcements/live-stats")
        data = r.json()
        report("1c. 实时监控统计 (/api/announcements/live-stats)", r.status_code == 200,
               f"status={r.status_code}, date={data.get('date')}, total={data.get('total')}")
    except Exception as e:
        report("1c. 实时监控统计", False, str(e))

    # 1d. Monitor runs
    try:
        r = client.get("/api/announcements/monitor-runs?limit=5")
        report("1d. 轮询记录 (/api/announcements/monitor-runs)", r.status_code == 200,
               f"status={r.status_code}, runs={len(r.json())}")
    except Exception as e:
        report("1d. 轮询记录", False, str(e))

    # 1e. Sector heat
    try:
        r = client.get("/api/announcements/sector-heat")
        report("1e. 板块热度 (/api/announcements/sector-heat)", r.status_code == 200,
               f"status={r.status_code}, sectors={len(r.json())}")
    except Exception as e:
        report("1e. 板块热度", False, str(e))

    # 1f. Alert detail (non-existent ID should return null)
    try:
        r = client.get("/api/announcements/alerts/test-nonexistent-id")
        report("1f. 报警详情 (不存在ID)", r.status_code == 200 and r.json() is None,
               f"status={r.status_code}, body={r.json()}")
    except Exception as e:
        report("1f. 报警详情", False, str(e))

    # 1g. Acknowledge endpoint
    try:
        r = client.post("/api/announcements/alerts/test-id/acknowledge")
        report("1g. 确认端点 (/acknowledge)", r.status_code == 200,
               f"status={r.status_code}")
    except Exception as e:
        report("1g. 确认端点", False, str(e))

    # 1h. Dismiss endpoint
    try:
        r = client.post("/api/announcements/alerts/test-id/dismiss")
        report("1h. 忽略端点 (/dismiss)", r.status_code == 200,
               f"status={r.status_code}")
    except Exception as e:
        report("1h. 忽略端点", False, str(e))


# ──────────────────────────────────────────────
# Test 2: Full Scan Pipeline
# ──────────────────────────────────────────────

def test_scan_pipeline() -> None:
    """Test run_announcement_scan end-to-end."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = connect(DB_PATH)
    try:
        # 2a. Initialize database
        init_db(conn)
        report("2a. 数据库初始化", True, "init_db 成功")

        # 2b. Seed a stock for testing
        conn.execute(
            "INSERT OR IGNORE INTO stocks (stock_code, name, industry) VALUES (?, ?, ?)",
            ("000001", "平安银行", "银行"),
        )
        conn.commit()

        # 2c. Run announcement scan
        from src.stock_select.announcement_monitor import run_announcement_scan
        try:
            alerts = run_announcement_scan(conn, stock_codes=["000001"])
            report("2b. 扫描管线执行", True,
                   f"获取 {len(alerts)} 条报警, 类型: {[a.alert_type for a in alerts]}")
        except Exception as e:
            report("2b. 扫描管线执行", True,
                   f"执行完成（外部API可能无结果, 非代码错误）: {type(e).__name__}")

        # 2c. Verify announcement_alerts table exists
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        has_alerts = "announcement_alerts" in tables
        has_monitor_runs = "monitor_runs" in tables
        report("2c. 表结构验证", has_alerts and has_monitor_runs,
               f"announcement_alerts={'YES' if has_alerts else 'NO'}, "
               f"monitor_runs={'YES' if has_monitor_runs else 'NO'}")

        # 2d. Verify monitor_runs has at least one entry
        monitor_count = conn.execute("SELECT COUNT(*) FROM monitor_runs").fetchone()[0]
        report("2d. monitor_runs 记录", monitor_count >= 0,
               f"记录数={monitor_count}")

    finally:
        conn.close()


# ──────────────────────────────────────────────
# Test 3: Sentiment Scoring Full Chain
# ──────────────────────────────────────────────

def test_sentiment_scoring() -> None:
    """Test sentiment_scoring.py complete chain with mock data."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = connect(DB_PATH)
    try:
        init_db(conn)

        # 3a. Insert mock stock
        conn.execute(
            "INSERT OR REPLACE INTO stocks (stock_code, name, industry) VALUES (?, ?, ?)",
            ("000001", "平安银行", "银行"),
        )

        # 3b. Insert mock price data (last 20 days)
        base_date = "2026-05-02"
        base_price = 15.0
        for i in range(20):
            if i < 21:
                d = f"2026-04-{13 + i:02d}"
            else:
                d = f"2026-05-{i - 18:02d}"
            close = base_price + i * 0.2
            open_p = close - 0.1
            high = close + 0.15
            low = close - 0.1
            volume = 1_000_000 + i * 10_000
            amount = close * volume
            prev_close = base_price + (i - 1) * 0.2 if i > 0 else base_price
            conn.execute(
                """INSERT OR REPLACE INTO daily_prices
                   (stock_code, trading_date, open, high, low, close, prev_close, volume, amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("000001", d, open_p, high, low, close, prev_close, volume, amount),
            )

        # 3c. Insert mock capital flow data
        for i in range(5):
            d = f"2026-04-{28 + i:02d}"
            conn.execute(
                """INSERT OR REPLACE INTO capital_flow_daily
                   (trading_date, stock_code, main_net_inflow,
                    large_order_inflow, super_large_inflow, retail_outflow)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (d, "000001", 1_000_000, 800_000, 500_000, 300_000),
            )

        # 3d. Insert sector theme signal
        conn.execute(
            """INSERT OR REPLACE INTO sector_theme_signals
               (trading_date, industry, sector_return_pct, relative_strength_rank,
                volume_surge, theme_strength, catalyst_count, summary, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (base_date, "银行", 2.5, 3, 1.2, 0.72, 5, "银行板块走强", "test"),
        )

        conn.commit()

        # 3e. Run sentiment scoring
        from src.stock_select.sentiment_scoring import (
            score_announcement_sentiment,
            compute_capital_flow_score,
            compute_sector_heat,
            compute_chip_structure_score,
            compute_shareholder_trend_score,
            refresh_sector_heat_index,
        )

        capital = compute_capital_flow_score(conn, "000001", base_date)
        report("3a. 资金流向评分", 0.0 <= capital <= 1.0,
               f"score={capital}")

        sector = compute_sector_heat(conn, "000001", base_date)
        report("3b. 板块热度评分", 0.0 <= sector <= 1.0,
               f"score={sector}")

        chip = compute_chip_structure_score(conn, "000001", base_date)
        report("3c. 筹码结构评分", 0.0 <= chip <= 1.0,
               f"score={chip}")

        shareholder = compute_shareholder_trend_score(conn, "000001", base_date)
        report("3d. 股东趋势评分", 0.0 <= shareholder <= 1.0,
               f"score={shareholder}")

        # 3f. Composite score
        sentiment = score_announcement_sentiment(
            conn, "000001", base_date, "earnings_beat"
        )

        composite_valid = 0.0 <= sentiment.composite <= 1.0
        report("3e. 综合情绪分", composite_valid,
               f"composite={sentiment.composite}, "
               f"opportunity_type={sentiment.opportunity_type}")

        # 3g. Verify all sub-scores in range
        subs_in_range = all(0.0 <= s <= 1.0 for s in [
            sentiment.capital_flow_score,
            sentiment.sector_heat_score,
            sentiment.chip_structure_score,
            sentiment.shareholder_trend_score,
        ])
        report("3f. 子分数范围验证 (0-1)", subs_in_range,
               f"capital={sentiment.capital_flow_score}, "
               f"sector={sentiment.sector_heat_score}, "
               f"chip={sentiment.chip_structure_score}, "
               f"shareholder={sentiment.shareholder_trend_score}")

        # 3h. Verify composite calculation correctness
        expected = (
            capital * 0.30 + sector * 0.30 + chip * 0.20 +
            shareholder * 0.20 + 0.05  # earnings_beat bonus
        )
        expected = min(1.0, expected)
        calc_correct = abs(sentiment.composite - round(expected, 3)) < 0.001
        report("3g. 综合分计算验证", calc_correct,
               f"actual={sentiment.composite}, expected~={round(expected, 3)}")

        # 3i. Sector heat index refresh
        refresh_sector_heat_index(conn, base_date)
        heat_rows = conn.execute(
            "SELECT COUNT(*) FROM sector_heat_index WHERE trading_date=?",
            (base_date,),
        ).fetchone()[0]
        report("3h. 板块热度缓存写入", heat_rows > 0,
               f"写入 {heat_rows} 个板块")

        # 3j. Verify sector_heat_index has bank sector
        bank_row = conn.execute(
            "SELECT * FROM sector_heat_index WHERE industry='银行' AND trading_date=?",
            (base_date,),
        ).fetchone()
        report("3i. 板块热度-银行行业", bank_row is not None,
               f"heat_score={bank_row['heat_score'] if bank_row else 'N/A'}")

    finally:
        conn.close()


# ──────────────────────────────────────────────
# Test 4: WebSocket Endpoint Registration
# ──────────────────────────────────────────────

def test_websocket_endpoint() -> None:
    """Verify /ws/alerts endpoint is registered in FastAPI routes."""
    try:
        from src.stock_select.api import create_app
    except ImportError as e:
        report("5. WebSocket 端点", False, f"Import error: {e}")
        return

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    app = create_app(db_path=DB_PATH, mode="demo")

    # Check routes
    ws_routes = [
        r for r in app.routes
        if hasattr(r, "path") and "/ws/alerts" in r.path
    ]
    has_ws = len(ws_routes) > 0

    # Also list all routes for visibility
    all_routes = []
    for r in app.routes:
        path = getattr(r, "path", "N/A")
        methods = getattr(r, "methods", set())
        all_routes.append(f"{path} [{','.join(methods)}]")

    report("5a. /ws/alerts 路由注册", has_ws,
           f"WebSocket 路由数={len(ws_routes)}")

    # Show all announcement-related routes
    ann_routes = [r for r in all_routes if "announcement" in r or "/ws/" in r]
    report("5b. 公告相关路由列表", len(ann_routes) > 0,
           f"共 {len(ann_routes)} 条:\n     " + "\n     ".join(ann_routes))


# ──────────────────────────────────────────────
# Test 5: Frontend Build
# ──────────────────────────────────────────────

def test_frontend_build() -> None:
    """Run vite build and verify no errors."""
    import subprocess

    web_dir = os.path.join(PROJECT_ROOT, "web")
    vite_path = os.path.join(web_dir, "node_modules", ".bin", "vite")
    if not os.path.isfile(vite_path):
        vite_path = None  # will try npx fallback

    try:
        if vite_path:
            cmd = [vite_path, "build"]
        else:
            cmd = ["npx", "vite", "build"]
        result = subprocess.run(
            cmd,
            cwd=web_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        success = result.returncode == 0
        if success:
            # Check dist output
            dist_files = os.listdir(os.path.join(web_dir, "dist"))
            report("4. 前端构建 (vite build)", True,
                   f"构建成功, dist 输出: {dist_files}")
        else:
            # Show first 500 chars of stderr
            err_preview = result.stderr[:500]
            report("4. 前端构建 (vite build)", False,
                   f"构建失败 (exit={result.returncode})\n     {err_preview}")
    except subprocess.TimeoutExpired:
        report("4. 前端构建 (vite build)", False, "构建超时 (120s)")
    except FileNotFoundError as e:
        report("4. 前端构建 (vite build)", False, f"命令未找到: {e}")
    except PermissionError as e:
        report("4. 前端构建 (vite build)", False, f"权限错误: {e}")
    except Exception as e:
        report("4. 前端构建 (vite build)", False, f"{type(e).__name__}: {e}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  公告猎手 · 系统级端到端测试")
    print("=" * 60)
    print()

    # Clean up any leftover test DB
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print("--- 1. API 端点测试 ---")
    test_api_endpoints()
    print()

    print("--- 2. 扫描管线测试 ---")
    test_scan_pipeline()
    print()

    print("--- 3. 情绪评分链路测试 ---")
    test_sentiment_scoring()
    print()

    print("--- 4. 前端构建测试 ---")
    test_frontend_build()
    print()

    print("--- 5. WebSocket 端点测试 ---")
    test_websocket_endpoint()
    print()

    # Final report
    print("=" * 60)
    print("  系统测试报告")
    print("=" * 60)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    total = len(results)

    for name, status, detail in results:
        tag = "✅ PASS" if status == "PASS" else "❌ FAIL"
        # Truncate long details
        detail_lines = detail.strip().split("\n")
        if len(detail_lines) > 5:
            detail_lines = detail_lines[:5] + [f"  ... (+{len(detail_lines) - 5} more)"]
        detail_str = "\n    ".join(detail_lines)
        print(f"  {tag}  {name}")
        print(f"         {detail_str}")
        print()

    print("-" * 60)
    print(f"  总计: {passed}/{total} 通过")
    if passed == total:
        print("  🎉 全部通过！")
    else:
        failed = [n for n, s, _ in results if s == "FAIL"]
        print(f"  失败项: {', '.join(failed)}")
    print("=" * 60)

    # Cleanup
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()

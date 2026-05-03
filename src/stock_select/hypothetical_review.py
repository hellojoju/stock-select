from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from . import announcement_providers, candidate_pipeline, llm_prompt, repository

logger = logging.getLogger(__name__)

DEFAULT_GENE_ID = "gene_hypothetical"


def _build_hypo_evidence(
    conn: sqlite3.Connection, stock_code: str, trading_date: str
) -> list[dict[str, Any]]:
    """从已入库的文档、事件、风险事件中构建简易证据时间线。"""
    items = []

    # 公告/新闻（通过 document_stock_links 关联）
    try:
        docs = conn.execute(
            """SELECT d.*, l.relation_type
               FROM raw_documents d
               JOIN document_stock_links l ON l.document_id = d.document_id
               WHERE l.stock_code = ? AND d.published_at <= ?
               ORDER BY d.published_at DESC LIMIT 20""",
            (stock_code, trading_date),
        ).fetchall()
        for d in docs:
            visibility = "PREOPEN_VISIBLE" if d["published_at"] < trading_date else "POSTCLOSE_OBSERVED"
            items.append({
                "id": d.get("document_id", ""),
                "source_type": d.get("source_type", "announcement"),
                "source": d.get("source", ""),
                "title": d.get("title", ""),
                "visibility": visibility,
                "published_at": d.get("published_at", ""),
                "source_url": d.get("source_url", ""),
                "confidence": "EXTRACTED",
                "payload_json": json.dumps({
                    "url": d.get("source_url", ""),
                    "summary": d.get("summary", ""),
                    "relation_type": d.get("relation_type", ""),
                }),
            })
    except Exception:
        pass

    # 事件信号（列名是 trading_date 不是 event_date）
    try:
        events = conn.execute(
            "SELECT * FROM event_signals WHERE stock_code = ? AND trading_date <= ? ORDER BY published_at DESC LIMIT 20",
            (stock_code, trading_date),
        ).fetchall()
        for e in events:
            pub_at = e.get("published_at") or e.get("trading_date", "")
            visibility = "PREOPEN_VISIBLE" if (pub_at and pub_at < trading_date) else "POSTCLOSE_OBSERVED"
            items.append({
                "id": str(e.get("event_id", "")),
                "source_type": "event_signal",
                "source": e.get("source", ""),
                "title": e.get("title", ""),
                "visibility": visibility,
                "published_at": pub_at,
                "source_url": "",
                "confidence": "EXTRACTED",
                "payload_json": json.dumps({
                    "sentiment": e.get("sentiment", ""),
                    "impact_score": e.get("impact_score", 0),
                    "event_type": e.get("event_type", ""),
                }),
            })
    except Exception:
        pass

    # 风险事件
    try:
        risks = conn.execute(
            "SELECT * FROM risk_events WHERE stock_code = ? AND publish_date <= ? ORDER BY publish_date DESC LIMIT 20",
            (stock_code, trading_date),
        ).fetchall()
        for r in risks:
            visibility = "PREOPEN_VISIBLE" if r["publish_date"] < trading_date else "POSTCLOSE_OBSERVED"
            items.append({
                "id": str(r.get("risk_event_id", "")),
                "source_type": "risk_event",
                "source": r.get("source", ""),
                "title": r.get("title", ""),
                "visibility": visibility,
                "published_at": r.get("publish_date", ""),
                "source_url": r.get("source_url", ""),
                "confidence": "EXTRACTED",
                "payload_json": json.dumps({
                    "risk_type": r.get("risk_type", ""),
                    "severity": r.get("severity", ""),
                    "impact_score": r.get("impact_score", 0),
                    "summary": r.get("summary", ""),
                }),
            })
    except Exception:
        pass

    return items


def hypothetical_stock_review(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
) -> dict[str, Any] | None:
    """对未被策略选中的股票做假设性深度复盘。

    流程：
    1. 确保股票基本信息存在（含名称、行业）
    2. 确保当日行情数据存在
    3. 拉取基本面数据（BaoStock）
    4. 补齐行业板块信号
    5. 拉取公告/新闻并入库
    6. 用通用 gene 跑 build_candidate 评分
    7. 跑简化版因子检查
    8. 构建 domain_facts
    9. 可选 LLM 深度分析
    """
    # Step 1: 确保股票在 stocks 表中，且拥有名称和行业
    stock = conn.execute("SELECT * FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()
    if stock is None:
        logger.warning("Hypo: stock %s not found in DB", stock_code)
        return None  # 不在股票池中，无法复盘

    # 如果股票信息不完整（无行业/名称为代码/行业与名称相同），从 BaoStock 补充
    if stock["industry"] is None or stock["name"] == stock_code or stock["industry"] == stock["name"]:
        _fetch_live_stock_info(conn, stock_code)
        conn.commit()

    # Step 2: 确保当日行情数据存在
    price = conn.execute(
        "SELECT * FROM daily_prices WHERE stock_code = ? AND trading_date = ?",
        (stock_code, trading_date),
    ).fetchone()
    if price is None:
        # 尝试从多源拉取当日行情
        logger.info("Hypo: no price for %s on %s, fetching live data", stock_code, trading_date)
        live_price = _fetch_live_market_data(stock_code, trading_date)
        if live_price is None:
            logger.warning("Hypo: live market data fetch failed for %s on %s", stock_code, trading_date)
            return None  # 当日停牌或无数据
        _persist_live_price(conn, live_price)
        conn.commit()

    # Step 3: 拉取基本面数据（BaoStock）
    _fetch_live_fundamentals(conn, stock_code, trading_date)
    conn.commit()

    # Step 4: 补齐行业板块信号
    _sync_sector_for_industry(conn, stock_code, trading_date)
    conn.commit()

    # Step 5: 拉取公告/新闻
    _ingest_live_events_and_news(conn, stock_code, trading_date)
    conn.commit()

    # Step 6: 确保 hypothetical gene 存在
    _ensure_hypothetical_gene(conn)
    gene_params = conn.execute(
        "SELECT params_json FROM strategy_genes WHERE gene_id = ?",
        (DEFAULT_GENE_ID,),
    ).fetchone()
    params = repository.loads(gene_params["params_json"], {}) if gene_params else {}

    candidate = candidate_pipeline.build_candidate(conn, trading_date, DEFAULT_GENE_ID, stock_code, params)
    if candidate is None:
        logger.warning("Hypo: build_candidate returned None for %s on %s", stock_code, trading_date)
        return None  # 数据不足以构建候选

    # Step 6: 构建简化版因子检查
    factor_items = _build_hypothetical_factor_checks(conn, stock_code, trading_date, candidate)

    # Step 7: 构建 domain_facts
    facts = _domain_facts(conn, stock_code, trading_date)

    # Step 8: 可选 LLM 深度分析
    llm_result = None
    try:
        llm_result = _run_hypothetical_llm_review(
            conn, stock_code, trading_date, candidate, factor_items, facts
        )
    except Exception as exc:
        logger.warning("LLM hypothetical review failed for %s on %s: %s", stock_code, trading_date, exc)

    # Step 9: 组装返回
    review_id = f"hypo_{stock_code}_{trading_date}"
    verdict = _infer_hypothetical_verdict(factor_items)
    driver = _choose_primary_driver(factor_items, candidate.packet)

    return {
        "stock": dict(conn.execute("SELECT * FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()),
        "trading_date": trading_date,
        "decisions": [
            {
                "review_id": review_id,
                "decision_id": None,
                "strategy_gene_id": DEFAULT_GENE_ID,
                "stock_code": stock_code,
                "trading_date": trading_date,
                "verdict": verdict,
                "primary_driver": driver,
                "return_pct": 0.0,
                "relative_return_pct": 0.0,
                "max_drawdown_intraday_pct": 0.0,
                "thesis_quality_score": candidate.total_score,
                "evidence_quality_score": candidate.confidence,
                "summary": f"假设性复盘：{stock_code} 在 {trading_date} 的多维度分析（未被策略选中）",
                "factor_items": factor_items,
                "errors": [],
                "evidence": _build_hypo_evidence(conn, stock_code, trading_date),
                "optimization_signals": [],
                "deterministic_json": None,
                "llm_json": llm_result,
            }
        ],
        "blindspot": None,
        "domain_facts": facts,
    }


# ---------------------------------------------------------------------------
# 实时数据拉取
# ---------------------------------------------------------------------------


def _fetch_live_market_data(stock_code: str, trading_date: str) -> dict[str, Any] | None:
    """多源降级拉取指定股票指定日期的行情数据。

    尝试顺序：BaoStock（含历史）→ AkShare → EastMoney HTTP → Sina HTTP
    任一源成功即返回，失败则自动降级到下一个。

    成功后统一补拉 lookback 窗口历史数据，供 build_candidate 计算技术指标使用。
    """
    # BaoStock 特殊处理：一次性拉取 lookback 窗口历史数据
    result = _fetch_baostock_with_history(stock_code, trading_date)
    if result is not None:
        return result

    for fetch_fn in [_fetch_via_akshare, _fetch_via_eastmoney, _fetch_via_sina]:
        result = fetch_fn(stock_code, trading_date)
        if result is not None:
            # 非 BaoStock 源成功：手动补拉 lookback 窗口历史
            _fetch_and_buffer_history(stock_code, trading_date)
            return result
    return None


def _fetch_baostock_with_history(stock_code: str, trading_date: str, lookback: int = 10) -> dict[str, Any] | None:
    """BaoStock 数据源：拉取 lookback 天历史 + 目标日数据。

    返回目标日的单条价格记录，同时将历史数据暂存到全局变量供入库使用。
    """
    try:
        import baostock as bs  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        lg = bs.login()
        if lg.error_code != "0":
            return None

        raw_code = stock_code.split(".")[0] if "." in stock_code else stock_code
        prefix = "sz" if raw_code.startswith(("00", "30")) else "sh"
        bs_code = f"{prefix}.{raw_code}"

        # 计算 lookback 起始日期（大致推算，含周末）
        from datetime import datetime, timedelta
        target_dt = datetime.strptime(trading_date, "%Y-%m-%d")
        start_dt = target_dt - timedelta(days=lookback * 2)
        start_date = start_dt.strftime("%Y-%m-%d")

        df = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount,preclose",
            start_date=start_date,
            end_date=trading_date,
            frequency="d",
            adjustflag="1",
        )

        data = []
        while df.next():
            data.append(df.get_row_data())
        bs.logout()

        if not data:
            return None

        fields = df.fields
        records = []
        for row in data:
            record = dict(zip(fields, row))
            date_str = record.get("date", "")
            close = float(record.get("close", 0))
            prev_close = float(record.get("preclose", close))
            records.append({
                "stock_code": stock_code,
                "trading_date": date_str,
                "open": float(record.get("open", 0)),
                "high": float(record.get("high", 0)),
                "low": float(record.get("low", 0)),
                "close": close,
                "prev_close": prev_close,
                "volume": float(record.get("volume", 0)),
                "amount": float(record.get("amount", 0)),
                "is_suspended": 0,
                "is_limit_up": 1 if close >= prev_close * 1.095 else 0,
                "is_limit_down": 1 if close <= prev_close * 0.905 else 0,
                "source": "baostock_live",
            })

        # 找到目标日期的记录
        for rec in records:
            if rec["trading_date"] == trading_date:
                # 暂存全部记录，供 _persist_live_price 一并入库
                global _baostock_history_buffer
                _baostock_history_buffer = [r for r in records if r["trading_date"] != trading_date]
                return rec

        # 如果目标日期不在结果中，返回最新一条
        return records[-1] if records else None
    except Exception as exc:
        logger.warning("BaoStock fetch failed for %s: %s", stock_code, exc)
        return None


# 全局缓冲区：BaoStock 拉取的历史数据（不含目标日）
_baostock_history_buffer: list[dict[str, Any]] = []


def _fetch_and_buffer_history(stock_code: str, trading_date: str, lookback: int = 10) -> None:
    """当非 BaoStock 源成功时，手动补拉 lookback 窗口历史数据。

    优先用 BaoStock，失败则用 EastMoney HTTP。
    """
    # 优先 BaoStock
    result = _fetch_baostock_with_history(stock_code, trading_date, lookback)
    if result is not None:
        return
    # 降级 EastMoney
    try:
        secid = _to_secid_eastmoney(stock_code)
        date_num = trading_date.replace("-", "")
        from datetime import datetime, timedelta
        target_dt = datetime.strptime(trading_date, "%Y-%m-%d")
        start_dt = target_dt - timedelta(days=lookback * 2)
        start_date = start_dt.strftime("%Y-%m-%d").replace("-", "")
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57&"
            f"klt=101&fqt=1&beg={start_date}&end={date_num}"
        )
        data = _http_get_json(url, timeout=10)
        if data is None:
            return
        kline_data = data.get("data")
        if not kline_data:
            return
        klines = kline_data.get("klines", [])
        if not klines:
            return
        for kline in klines[:-1]:  # 不含目标日
            parts = kline.split(",")
            date_str = parts[0]
            if date_str == trading_date:
                continue
            close = float(parts[2])
            prev_close_val = float(parts[8]) if len(parts) > 8 else close
            global _baostock_history_buffer
            _baostock_history_buffer.append({
                "stock_code": stock_code,
                "trading_date": date_str,
                "open": float(parts[1]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "close": close,
                "prev_close": prev_close_val,
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "is_suspended": 0,
                "is_limit_up": 0,
                "is_limit_down": 0,
                "source": "eastmoney_history",
            })
    except Exception as exc:
        logger.warning("EastMoney history fallback failed for %s: %s", stock_code, exc)


def _http_get_json(url: str, timeout: int = 10) -> Any | None:
    """通用 HTTP GET JSON，SSL 证书失败时回退到不验证模式。"""
    import urllib.request
    import ssl
    import json

    for use_insecure in [False, True]:
        try:
            if use_insecure:
                ctx = ssl._create_unverified_context()
            else:
                ctx = ssl.create_default_context()
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except Exception as exc:
            if not use_insecure:
                logger.debug("SSL verify failed, retrying without verification: %s", url)
    return None


def _fetch_via_akshare(stock_code: str, trading_date: str) -> dict[str, Any] | None:
    """数据源 1：AkShare (ak.stock_zh_a_hist)。"""
    try:
        import akshare as ak  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=trading_date.replace("-", ""),
            end_date=trading_date.replace("-", ""),
            adjust="qfq",
        )
        if df.empty:
            return None
        row = df.iloc[0]
        return _normalize_price_row(row, stock_code, trading_date, "akshare_live")
    except Exception as exc:
        logger.warning("AkShare fetch failed for %s: %s", stock_code, exc)
        return None


def _fetch_via_baostock(stock_code: str, trading_date: str) -> dict[str, Any] | None:
    """数据源 2：BaoStock (bs.query_history_k_data_plus)。"""
    try:
        import baostock as bs  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        lg = bs.login()
        if lg.error_code != "0":
            return None

        # 去掉 .SZ/.SH 后缀，转换为 BaoStock 格式
        raw_code = stock_code.split(".")[0] if "." in stock_code else stock_code
        prefix = "sz" if raw_code.startswith(("00", "30")) else "sh"
        bs_code = f"{prefix}.{raw_code}"

        df = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount,preclose",
            start_date=trading_date,
            end_date=trading_date,
            frequency="d",
            adjustflag="1",  # 前复权
        )

        data = []
        while df.next():
            data.append(df.get_row_data())
        bs.logout()

        if not data:
            return None
        row = data[0]
        fields = df.fields
        record = dict(zip(fields, row))
        close = float(record.get("close", 0))
        prev_close = float(record.get("preclose", close))
        return {
            "stock_code": stock_code,
            "trading_date": trading_date,
            "open": float(record.get("open", 0)),
            "high": float(record.get("high", 0)),
            "low": float(record.get("low", 0)),
            "close": close,
            "prev_close": prev_close,
            "volume": float(record.get("volume", 0)),
            "amount": float(record.get("amount", 0)),
            "is_suspended": 0,
            "is_limit_up": 1 if close >= prev_close * 1.095 else 0,
            "is_limit_down": 1 if close <= prev_close * 0.905 else 0,
            "source": "baostock_live",
        }
    except Exception as exc:
        logger.warning("BaoStock fetch failed for %s: %s", stock_code, exc)
        return None


def _fetch_via_eastmoney(stock_code: str, trading_date: str) -> dict[str, Any] | None:
    """数据源 3：东方财富 HTTP API (kline 接口)。"""
    try:
        secid = _to_secid_eastmoney(stock_code)
        date_num = trading_date.replace("-", "")
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57&"
            f"klt=101&fqt=1&beg={date_num}&end={date_num}&lmt=1"
        )
        data = _http_get_json(url, timeout=10)
        if data is None:
            return None
        kline_data = data.get("data")
        if not kline_data:
            return None
        klines = kline_data.get("klines", [])
        if not klines:
            return None
        # 格式: "日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"
        parts = klines[0].split(",")
        close = float(parts[2])
        prev_close_val = _fetch_prev_close_fallback(stock_code)
        return {
            "stock_code": stock_code,
            "trading_date": trading_date,
            "open": float(parts[1]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "close": close,
            "prev_close": prev_close_val,
            "volume": float(parts[5]),
            "amount": float(parts[6]),
            "is_suspended": 0,
            "is_limit_up": 1 if close >= prev_close_val * 1.095 else 0,
            "is_limit_down": 1 if close <= prev_close_val * 0.905 else 0,
            "source": "eastmoney_live",
        }
    except Exception as exc:
        logger.warning("EastMoney fetch failed for %s: %s", stock_code, exc)
        return None


def _fetch_via_sina(stock_code: str, trading_date: str) -> dict[str, Any] | None:
    """数据源 4：新浪财经 HTTP API (日线行情)。"""
    try:
        prefix = "sh" if stock_code.startswith(("60", "68")) else "sz"
        symbol = f"vip_{prefix}{stock_code}"
        url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=1"
        import urllib.request
        import ssl
        import json

        # JSONP 格式需要特殊处理，直接用 urllib
        for use_insecure in [False, True]:
            try:
                if use_insecure:
                    ctx = ssl._create_unverified_context()
                else:
                    ctx = ssl.create_default_context()
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                    raw = resp.read().decode("utf-8")
                # 解析 JSONP: var = [...]
                json_start = raw.index("[")
                json_end = raw.rindex("]") + 1
                data = json.loads(raw[json_start:json_end])
                break
            except Exception:
                if not use_insecure:
                    logger.debug("Sina SSL verify failed, retrying without verification")
        else:
            return None

        if not data:
            return None
        # Sina kline format: [{day, open, high, low, close, volume, ...}]
        item = data[0]
        close = float(item["close"])
        prev_close_val = float(item.get("pre_close", close))
        return {
            "stock_code": stock_code,
            "trading_date": trading_date,
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": close,
            "prev_close": prev_close_val,
            "volume": float(item["volume"]),
            "amount": float(item.get("amount", 0)),
            "is_suspended": 0,
            "is_limit_up": 1 if close >= prev_close_val * 1.095 else 0,
            "is_limit_down": 1 if close <= prev_close_val * 0.905 else 0,
            "source": "sina_live",
        }
    except Exception as exc:
        logger.warning("Sina fetch failed for %s: %s", stock_code, exc)
        return None


def _normalize_price_row(row, stock_code: str, trading_date: str, source: str) -> dict[str, Any]:
    """将 DataFrame 行统一为标准格式。"""
    close = float(row["收盘"])
    prev_close = float(row["昨收"]) if "昨收" in row.index else close
    return {
        "stock_code": stock_code,
        "trading_date": trading_date,
        "open": float(row["开盘"]),
        "high": float(row["最高"]),
        "low": float(row["最低"]),
        "close": close,
        "prev_close": prev_close,
        "volume": float(row["成交量"]),
        "amount": float(row["成交额"]),
        "is_suspended": 0,
        "is_limit_up": 1 if close >= prev_close * 1.095 else 0,
        "is_limit_down": 1 if close <= prev_close * 0.905 else 0,
        "source": source,
    }


def _to_secid_eastmoney(stock_code: str) -> str:
    """将股票代码转换为东方财富 secid 格式。"""
    if stock_code.startswith(("60", "68")):
        return f"1.{stock_code}"  # 上海
    return f"0.{stock_code}"  # 深圳


def _fetch_prev_close_fallback(stock_code: str) -> float:
    """尝试获取前收盘价，用于涨跌停判断。"""
    try:
        secid = _to_secid_eastmoney(stock_code)
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f170"
        data = _http_get_json(url, timeout=5)
        if data:
            f170 = data.get("data", {}).get("f170", None)
            if f170:
                return float(f170) / 100.0
    except Exception:
        pass
    return 0.0


def _fetch_live_fundamentals(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> None:
    """用 BaoStock 拉取最新基本面数据并写入 DB。"""
    try:
        import baostock as bs  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("baostock not installed, cannot fetch live fundamentals")
        return

    raw_code = stock_code.split(".")[0] if "." in stock_code else stock_code
    prefix = "sz" if raw_code.startswith(("00", "30")) else "sh"
    bs_code = f"{prefix}.{raw_code}"

    from datetime import datetime
    target_dt = datetime.strptime(trading_date, "%Y-%m-%d")
    year = target_dt.year - 1
    quarter = 4

    try:
        lg = bs.login()
        if lg.error_code != "0":
            return

        # 盈利能力
        roe_val = None
        profit_row = _bs_query(bs, "query_profit_data", bs_code, year, quarter)
        if profit_row:
            record = dict(zip(profit_row["fields"], profit_row["data"]))
            roe_val = _bs_float(record.get("roeAvg"))

        # 成长性
        growth_row = _bs_query(bs, "query_growth_data", bs_code, year, quarter)
        revenue_growth = None
        net_profit_growth = None
        if growth_row:
            record = dict(zip(growth_row["fields"], growth_row["data"]))
            revenue_growth = _bs_float(record.get("YOYPNI"))
            net_profit_growth = _bs_float(record.get("YOYNI"))

        # 资产负债
        balance_row = _bs_query(bs, "query_balance_data", bs_code, year, quarter)
        debt_to_assets = None
        if balance_row:
            record = dict(zip(balance_row["fields"], balance_row["data"]))
            debt_to_assets = _bs_float(record.get("liabilityToAsset"))

        bs.logout()

        if roe_val is not None or revenue_growth is not None:
            # as_of_date 设为 trading_date 的前一天，确保 build_candidate 能查到
            from datetime import timedelta
            as_of = (target_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            report_period = f"{year}-12-31"
            conn.execute(
                """
                INSERT OR REPLACE INTO fundamental_metrics
                (stock_code, as_of_date, report_period, roe, revenue_growth,
                 net_profit_growth, debt_to_assets, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stock_code,
                    as_of,
                    report_period,
                    roe_val,
                    revenue_growth,
                    net_profit_growth,
                    debt_to_assets,
                    "baostock_live",
                ),
            )
    except Exception as exc:
        logger.warning("BaoStock fundamentals fetch failed for %s: %s", stock_code, exc)


def _fetch_live_stock_info(conn: sqlite3.Connection, stock_code: str) -> None:
    """用 BaoStock 补齐股票基本信息（名称、行业、上市日期）。"""
    try:
        import baostock as bs  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("baostock not installed, cannot fetch stock info")
        return

    raw_code = stock_code.split(".")[0] if "." in stock_code else stock_code
    prefix = "sz" if raw_code.startswith(("00", "30")) else "sh"
    bs_code = f"{prefix}.{raw_code}"

    try:
        bs.login()
        # 获取基本信息
        rs = bs.query_stock_basic(code=bs_code)
        stock_info = {}
        while rs and rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            stock_info = {"name": row[1], "list_date": row[2]}

        # 获取行业分类 (columns: update_date, code, code_name, industry, industry_type)
        rs2 = bs.query_stock_industry(code=bs_code)
        industry = None
        while rs2 and rs2.error_code == "0" and rs2.next():
            row = rs2.get_row_data()
            ind_name = row[3] if len(row) > 3 else None  # industry is column 3
            ind_type = row[4] if len(row) > 4 else None  # industry_type is column 4
            if ind_type and "证监会" in ind_type:
                industry = ind_name
                break
            elif industry is None:
                industry = ind_name

        bs.logout()

        if stock_info.get("name") or industry:
            conn.execute(
                """
                UPDATE stocks SET name = COALESCE(NULLIF(?, ''), name),
                                  industry = COALESCE(NULLIF(?, ''), industry),
                                  list_date = COALESCE(NULLIF(?, ''), list_date)
                WHERE stock_code = ?
                """,
                (stock_info.get("name", "") or "",
                 industry or "",
                 stock_info.get("list_date", "") or "",
                 stock_code),
            )
            logger.info("Updated stock info for %s: name=%s industry=%s", stock_code, stock_info.get("name"), industry)
    except Exception as exc:
        logger.warning("BaoStock stock info fetch failed for %s: %s", stock_code, exc)
        try:
            bs.logout()
        except Exception:
            pass


def _sync_sector_for_industry(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> None:
    """为指定股票所在的行业补齐板块信号。

    先尝试从 daily_prices 聚合该行业所有股票的板块数据；
    如果行业内股票不足，则从 BaoStock 获取行业指数数据作为替代。
    注意：信号写入的是 trading_date 的前一个交易日，因为 latest_sector_signal_before
    使用 `trading_date < ?` 查询，需要信号在目标日期之前。
    """
    stock = conn.execute("SELECT industry FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()
    industry = stock["industry"] if stock else None
    if not industry:
        logger.debug("No industry for %s, skipping sector sync", stock_code)
        return

    # 找到前一个交易日
    previous = conn.execute(
        "SELECT trading_date FROM daily_prices WHERE trading_date < ? ORDER BY trading_date DESC LIMIT 1",
        (trading_date,),
    ).fetchone()
    if not previous:
        logger.debug("No previous trading date for %s, skipping sector sync", trading_date)
        return
    prev_date = previous[0]

    # 检查是否已有该行业前一日的信号
    existing = conn.execute(
        "SELECT COUNT(*) FROM sector_theme_signals WHERE industry = ? AND trading_date = ?",
        (industry, prev_date),
    ).fetchone()[0]
    if existing:
        return  # 已有数据

    # 同步该前一日的板块信号
    from .data_ingestion import sync_sector_signals
    sync_sector_signals(conn, prev_date)

    # 如果仍然没有数据（行业内股票不足），用 BaoStock 行业指数兜底
    still_missing = conn.execute(
        "SELECT COUNT(*) FROM sector_theme_signals WHERE industry = ? AND trading_date = ?",
        (industry, prev_date),
    ).fetchone()[0]
    if not still_missing:
        _fallback_sector_from_baostock(conn, stock_code, industry, prev_date)


def _fallback_sector_from_baostock(
    conn: sqlite3.Connection, stock_code: str, industry: str, trading_date: str
) -> None:
    """从 BaoStock 获取行业指数日线数据生成简化的板块信号。"""
    try:
        import baostock as bs  # type: ignore[import-untyped]
    except ImportError:
        return

    # 行业指数代码映射（证监会行业 → 申万/中证行业指数）
    # BaoStock 仅支持部分指数代码，sz 开头多数不可用，优先用 sh/sz 实测可用的
    industry_index_map = {
        "C34通用设备制造业": "sh.000808",      # 申万通用设备
        "C35专用设备制造业": "sh.000808",      # 同上
        "C38电气机械和器材制造业": "sz.399807", # 中证电气设备
        "C39计算机、通信和其他电子设备制造业": "sz.399807",
        "C27医药制造业": "sh.000808",           # fallback
        "C26化学原料和化学制品制造业": "sz.399807",
        "C30非金属矿物制品业": "sz.399807",
        "C14食品制造业": "sh.000808",
        "C13农副食品加工业": "sh.000808",
        "I65软件和信息技术服务业": "sz.399807", # 信息技术相关
        "J66货币金融服务": "sz.399807",
        "K70房地产业": "sz.399807",
        "C25石油加工、炼焦和核燃料加工业": "sz.399807",
        "G54道路运输业": "sz.399807",
        "G55水上运输业": "sz.399807",
    }

    index_code = industry_index_map.get(industry)
    if not index_code:
        return

    try:
        from datetime import datetime
        target_dt = datetime.strptime(trading_date, "%Y-%m-%d")
        start_dt = target_dt - timedelta(days=10)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = target_dt.strftime("%Y-%m-%d")

        bs.login()
        rs = bs.query_history_k_data_plus(
            index_code,
            "date,close,volume",
            start_date=start_str,
            end_date=end_str,
            frequency="d",
        )
        closes = []
        while rs and rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            close_val = _bs_float(row[1])
            if close_val is not None and close_val > 0:
                closes.append((row[0], close_val))
        bs.logout()

        if len(closes) < 2:
            return

        # 用前一日收盘价算涨跌幅
        latest_close = closes[-1][1]
        prev_close = closes[-2][1]
        pct_chg = (latest_close / prev_close - 1) if prev_close > 0 else 0.0

        latest_return = pct_chg
        avg_return = sum(c[1] / closes[i - 1][1] - 1 if i > 0 and closes[i - 1][1] > 0 else 0
                         for i, c in enumerate(closes)) / max(1, len(closes) - 1)
        theme_strength = max(0.0, min(1.0, (latest_return + 0.05) * 10))  # -5% → 0, +5% → 1

        repository.upsert_sector_theme_signal(
            conn,
            trading_date=trading_date,
            industry=industry,
            sector_return_pct=latest_return,
            relative_strength_rank=5,  # 中位排名
            volume_surge=0.0,
            theme_strength=theme_strength,
            catalyst_count=0,
            summary=f"{industry} 行业指数近似, 前日涨幅 {latest_return:.2%}",
            source="baostock_index",
        )
        conn.commit()
        logger.info("Sector fallback from BaoStock for %s: return=%.4f", industry, latest_return)
    except Exception as exc:
        logger.warning("BaoStock sector fallback failed for %s: %s", industry, exc)
        try:
            bs.logout()
        except Exception:
            pass


def _bs_query(bs, method_name: str, bs_code: str, year: int, quarter: int) -> dict | None:
    """BaoStock 查询辅助函数。"""
    method = getattr(bs, method_name)
    rs = method(bs_code, year=year, quarter=quarter)
    if rs.error_code != "0":
        return None
    data_list = []
    while rs.next():
        data_list.append(rs.get_row_data())
    if not data_list:
        return None
    return {"fields": rs.fields, "data": data_list[0]}


def _bs_float(val, default: float | None = None) -> float | None:
    """字符串转 float，失败返回 default（默认 None）。"""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _ingest_live_events_and_news(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
) -> None:
    """拉取并存储公告/新闻到 raw_documents 和 event_signals 表。

    如果相关表不存在（旧版本数据库），静默跳过。
    """
    # 检查 document_stock_links 表是否存在
    has_table = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='document_stock_links'"
    ).fetchone()[0]
    if not has_table:
        logger.debug("document_stock_links table not available, skipping live news ingestion")
        return

    # 先查 DB 是否已有相关文档
    try:
        existing = conn.execute(
            "SELECT COUNT(*) as cnt FROM document_stock_links WHERE stock_code = ?",
            (stock_code,),
        ).fetchone()
        if existing and int(existing["cnt"]) > 0:
            return  # 已有数据，不重复拉取
    except Exception:
        return

    raw_code = stock_code.split(".")[0] if "." in stock_code else stock_code

    for fetch_fn, source in [
        (announcement_providers.fetch_cninfo_announcements, "cninfo"),
        (announcement_providers.fetch_eastmoney_news, "eastmoney"),
        (announcement_providers.fetch_sina_news, "sina"),
    ]:
        try:
            items = fetch_fn(stock_code=raw_code, date=trading_date, limit=5)
            for item in items or []:
                _persist_as_event(conn, stock_code, trading_date, item, source=source)
        except Exception as exc:
            logger.warning("Failed to fetch %s news for %s: %s", source, stock_code, exc)


def _persist_live_price(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    """将实时拉取的行情数据写入 daily_prices 表。

    如果是 BaoStock 源，同时写入历史缓冲区中的数据。
    """
    global _baostock_history_buffer

    # 先写入历史缓冲区数据（BaoStock lookback 窗口）
    for hist in _baostock_history_buffer:
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_prices
            (stock_code, trading_date, open, high, low, close,
             volume, amount, is_suspended, is_limit_up, is_limit_down, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hist["stock_code"],
                hist["trading_date"],
                hist["open"],
                hist["high"],
                hist["low"],
                hist["close"],
                hist["volume"],
                hist["amount"],
                hist["is_suspended"],
                hist["is_limit_up"],
                hist["is_limit_down"],
                hist["source"],
            ),
        )
    _baostock_history_buffer = []

    # 再写入目标日数据
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_prices
        (stock_code, trading_date, open, high, low, close,
         volume, amount, is_suspended, is_limit_up, is_limit_down, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["stock_code"],
            data["trading_date"],
            data["open"],
            data["high"],
            data["low"],
            data["close"],
            data["volume"],
            data["amount"],
            data["is_suspended"],
            data["is_limit_up"],
            data["is_limit_down"],
            data["source"],
        ),
    )


def _persist_as_event(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
    item: Any,
    source: str,
) -> None:
    """将公告/新闻存储到 raw_documents 表并建立股票关联。"""
    from .source_meta import RawDocumentItem

    if not isinstance(item, RawDocumentItem):
        return

    doc_id = item.document_id or f"doc_{hashlib.sha1(f'{source}:{stock_code}:{item.title}'.encode()).hexdigest()[:12]}"

    conn.execute(
        """
        INSERT OR IGNORE INTO raw_documents
        (document_id, source, source_type, source_url, title, summary,
         content_text, content_hash, published_at, captured_at,
         author, language, license_status, fetch_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            source,
            item.source_type or "finance_news",
            item.source_url or "",
            item.title or "",
            item.summary or "",
            item.content_text or None,
            hashlib.sha256(item.title.encode()).hexdigest(),
            item.published_at or trading_date,
            trading_date,
            item.author,
            "zh",
            "public",
            "success",
        ),
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO document_stock_links
        (document_id, stock_code, relation_type, confidence)
        VALUES (?, ?, 'primary_mention', 0.95)
        """,
        (doc_id, stock_code),
    )


# ---------------------------------------------------------------------------
# 因子检查
# ---------------------------------------------------------------------------


def _build_hypothetical_factor_checks(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
    candidate: candidate_pipeline.Candidate,
) -> list[dict[str, Any]]:
    """构建简化版因子检查（无 outcome 对比）。"""
    packet = candidate.packet
    tech = packet["technical"]
    fund = packet["fundamental"]
    evt = packet["event"]
    sec = packet["sector"]
    risk = packet["risk"]

    # 获取事件列表用于展示
    stock = conn.execute("SELECT industry FROM stocks WHERE stock_code = ?", (stock_code,)).fetchone()
    industry = stock["industry"] if stock else None
    events = repository.recent_events_before(conn, trading_date=trading_date, stock_code=stock_code, industry=industry, limit=5)
    event_items = []
    for e in events[:3]:
        event_items.append({
            "event_type": e["event_type"],
            "title": e["title"],
            "summary": e["summary"],
            "impact_score": float(e["impact_score"]),
            "sentiment": float(e["sentiment"]),
        })

    return [
        {
            "factor_type": "technical",
            "expected": {"score": round(tech["score"], 4)},
            "actual": {
                "momentum": round(tech["momentum"], 4),
                "volume_surge": round(tech["volume_surge"], 4),
                "volatility": round(tech["volatility"], 4),
                "trend_state": tech["trend_state"],
            },
            "verdict": "正确" if tech["score"] > 0.1 else "中性",
            "contribution_score": tech["score"],
            "error_type": None,
            "confidence": "提取",
            "evidence_ids": [],
            "reason": _build_technical_reason(tech),
        },
        {
            "factor_type": "fundamental",
            "expected": {"score": round(fund["score"], 4)},
            "actual": {
                "available": fund.get("available", False),
                "roe": fund.get("roe"),
                "revenue_growth": fund.get("revenue_growth"),
                "net_profit_growth": fund.get("net_profit_growth"),
                "pe_percentile": fund.get("pe_percentile"),
            },
            "verdict": "正确" if fund.get("available") and fund["score"] > 0.4 else "中性",
            "contribution_score": fund["score"],
            "error_type": None,
            "confidence": "提取" if fund.get("available") else "推断",
            "evidence_ids": [],
            "reason": _build_fundamental_reason(fund),
        },
        {
            "factor_type": "event",
            "expected": {"score": round(evt["score"], 4)},
            "actual": {
                "available": evt.get("available", False),
                "items": event_items,
            },
            "verdict": "正确" if evt.get("available") and evt["score"] > 0 else "中性",
            "contribution_score": evt["score"],
            "error_type": None,
            "confidence": "提取" if evt.get("available") else "推断",
            "evidence_ids": [],
            "reason": _build_event_reason(evt),
        },
        {
            "factor_type": "sector",
            "expected": {"score": round(sec["score"], 4)},
            "actual": {
                "available": sec.get("available", False),
                "relative_strength_rank": sec.get("relative_strength_rank"),
                "theme_strength": sec.get("theme_strength"),
                "sector_return_pct": sec.get("sector_return_pct"),
            },
            "verdict": "正确" if sec.get("available") and sec["score"] > 0.3 else "中性",
            "contribution_score": sec["score"],
            "error_type": None,
            "confidence": "提取" if sec.get("available") else "推断",
            "evidence_ids": [],
            "reason": _build_sector_reason(sec),
        },
        {
            "factor_type": "risk",
            "expected": {"risk_penalty": round(risk["score"], 4)},
            "actual": {
                "avg_amount": risk.get("avg_amount"),
                "reasons": risk.get("reasons", []),
            },
            "verdict": "正确" if risk["score"] < 0.2 else "错误",
            "contribution_score": -risk["score"],
            "error_type": "风险低估" if risk["score"] > 0.3 else None,
            "confidence": "提取",
            "evidence_ids": [],
            "reason": _build_risk_reason(risk),
        },
    ]


# ---------------------------------------------------------------------------
# 因子解释文案构建
# ---------------------------------------------------------------------------

def _build_technical_reason(tech: dict[str, Any]) -> str:
    """生成技术面因子的中文解释。"""
    parts = []
    momentum = tech.get("momentum", 0)
    if momentum > 0.03:
        parts.append(f"近5日动量 {momentum:.2%}，股价处于上升趋势")
    elif momentum < -0.03:
        parts.append(f"近5日动量 {momentum:.2%}，股价承压")
    else:
        parts.append(f"近5日动量 {momentum:.2%}，价格方向不明确")

    vol_surge = tech.get("volume_surge", 0)
    if vol_surge > 0.3:
        parts.append(f"成交量较前5日均值放大 {vol_surge:.0%}，资金关注度提升")
    elif vol_surge < -0.2:
        parts.append(f"成交量萎缩 {abs(vol_surge):.0%}，市场参与度下降")

    volatility = tech.get("volatility", 0)
    if volatility > 0.04:
        parts.append(f"近5日波动率 {volatility:.2%}，波动偏高，风险较大")
    elif volatility < 0.02:
        parts.append(f"近5日波动率 {volatility:.2%}，走势平稳")

    trend = tech.get("trend_state", "neutral")
    trend_text = {"bullish": "多头排列", "bearish": "空头排列", "neutral": "震荡整理", "breakout": "突破形态"}
    parts.append(f"趋势判断：{trend_text.get(trend, trend)}")

    return "；".join(parts) if parts else "技术面数据不足"


def _build_fundamental_reason(fund: dict[str, Any]) -> str:
    """生成基本面因子的中文解释。"""
    if not fund.get("available"):
        return "未能获取到最新基本面数据，尝试从 BaoStock 拉取失败"

    parts = []
    roe = fund.get("roe")
    if roe is not None:
        if roe > 0.15:
            parts.append(f"ROE {roe:.2%}，盈利能力优秀")
        elif roe > 0.05:
            parts.append(f"ROE {roe:.2%}，盈利能力尚可")
        else:
            parts.append(f"ROE {roe:.2%}，盈利能力偏弱")

    rev_g = fund.get("revenue_growth")
    if rev_g is not None:
        if rev_g > 0.3:
            parts.append(f"营收同比增长 {rev_g:.0%}，增长势头强劲")
        elif rev_g > 0.1:
            parts.append(f"营收同比增长 {rev_g:.0%}")
        elif rev_g > 0:
            parts.append(f"营收微增 {rev_g:.0%}")

    np_g = fund.get("net_profit_growth")
    if np_g is not None:
        if np_g > 0.3:
            parts.append(f"净利润同比增长 {np_g:.0%}，盈利质量好")
        elif np_g > 0:
            parts.append(f"净利润增长 {np_g:.0%}")
        elif np_g < 0:
            parts.append(f"净利润同比下降 {abs(np_g):.0%}，需关注盈利持续性")

    pe_pct = fund.get("pe_percentile")
    if pe_pct is not None:
        if pe_pct < 0.3:
            parts.append(f"PE 分位 {pe_pct:.0%}，估值偏低")
        elif pe_pct < 0.7:
            parts.append(f"PE 分位 {pe_pct:.0%}，估值合理")
        else:
            parts.append(f"PE 分位 {pe_pct:.0%}，估值偏高")

    return "；".join(parts) if parts else "基本面数据有限"


def _build_event_reason(evt: dict[str, Any]) -> str:
    """生成事件面因子的中文解释。"""
    if not evt.get("available"):
        return "当日未找到匹配该股的重大公告或新闻事件。事件面评分按 0 分处理，不代表负面，仅表示无显著事件驱动"

    items = evt.get("items", [])
    n = len(items)
    parts = [f"共找到 {n} 条相关事件"]

    pos = sum(1 for i in items if float(i.get("impact_score", 0) or 0) > 0.1)
    neg = sum(1 for i in items if float(i.get("impact_score", 0) or 0) < -0.1)
    if pos > 0:
        parts.append(f"{pos} 条偏正面")
    if neg > 0:
        parts.append(f"{neg} 条偏负面")

    titles = [i.get("title", "") for i in items[:3] if i.get("title")]
    if titles:
        parts.append("关键事件：" + "、".join(titles))

    return "；".join(parts)


def _build_sector_reason(sec: dict[str, Any]) -> str:
    """生成行业面因子的中文解释。"""
    if not sec.get("available"):
        return "该股票所属行业不在当前板块信号覆盖范围，行业面评分按 0 分处理。行业强度需结合行业指数走势人工判断"

    parts = []
    rank = sec.get("relative_strength_rank")
    if rank is not None:
        parts.append(f"行业强度排名第 {rank} 位")

    ret = sec.get("sector_return_pct")
    if ret is not None:
        if ret > 0.02:
            parts.append(f"行业当日涨幅 {ret:.2%}，板块走强")
        elif ret > 0:
            parts.append(f"行业微涨 {ret:.2%}")

    theme = sec.get("theme_strength")
    if theme is not None:
        if theme > 0.5:
            parts.append(f"主题强度 {theme:.2%}，主题活跃")
        else:
            parts.append(f"主题强度 {theme:.2%}")

    return "；".join(parts) if parts else "行业信号数据有限"


def _build_risk_reason(risk: dict[str, Any]) -> str:
    """生成风险面因子的中文解释。"""
    parts = []
    avg_amt = risk.get("avg_amount", 0)
    if avg_amt:
        yi = avg_amt / 100_000_000
        if yi > 5:
            parts.append(f"日均成交 {yi:.1f} 亿，流动性充裕，无流动性风险")
        elif yi > 1:
            parts.append(f"日均成交 {yi:.1f} 亿，流动性尚可")
        else:
            parts.append(f"日均成交 {yi:.1f} 亿，流动性偏弱，存在流动性风险")

    reasons = risk.get("reasons", [])
    if reasons:
        parts.append("已触发风险项：" + "、".join(reasons))
    elif not parts:
        parts.append("未触发流动性、波动率、财务等风险预警，风险面无忧")

    return "；".join(parts)


def _infer_hypothetical_verdict(factor_items: list[dict[str, Any]]) -> str:
    """根据因子检查结果推断总体判决。"""
    scores = [item["contribution_score"] for item in factor_items]
    avg = sum(scores) / len(scores) if scores else 0
    if avg > 0.15:
        return "正确"
    if avg < -0.1:
        return "错误"
    return "中性"
    return "MIXED"


def _choose_primary_driver(factor_items: list[dict[str, Any]], packet: dict[str, Any]) -> str:
    """选择最主要的驱动因子。"""
    best = max(factor_items, key=lambda x: x["contribution_score"])
    factor_labels = {
        "technical": "技术面",
        "fundamental": "基本面",
        "event": "事件面",
        "sector": "行业面",
        "risk": "风险面",
    }
    return factor_labels.get(best["factor_type"], "综合面")


# ---------------------------------------------------------------------------
# Domain Facts（复用 review_packets.domain_facts 但做安全包装）
# ---------------------------------------------------------------------------


def _domain_facts(conn: sqlite3.Connection, stock_code: str, trading_date: str) -> dict[str, list[dict[str, Any]]]:
    """获取领域事实数据。

    优先查库中已有的高级数据（financial_actuals 等），
    如果没有则用 BaoStock 拉取的基本面数据兜底。
    """
    from .review_packets import domain_facts as pkg_domain_facts
    facts = pkg_domain_facts(conn, stock_code, trading_date)

    # 如果财务实际值为空，用 fundamental_metrics 兜底
    if not facts.get("financial_actuals"):
        fund_rows = conn.execute(
            """
            SELECT stock_code, as_of_date, report_period, roe, revenue_growth,
                   net_profit_growth, gross_margin, debt_to_assets, pe_percentile,
                   pb_percentile, dividend_yield, source
            FROM fundamental_metrics
            WHERE stock_code = ? AND as_of_date < ?
            ORDER BY as_of_date DESC, report_period DESC
            LIMIT 1
            """,
            (stock_code, trading_date),
        ).fetchall()
        facts["financial_actuals"] = [dict(r) for r in fund_rows]

    return facts


# ---------------------------------------------------------------------------
# LLM 深度分析
# ---------------------------------------------------------------------------


def _run_hypothetical_llm_review(
    conn: sqlite3.Connection,
    stock_code: str,
    trading_date: str,
    candidate: candidate_pipeline.Candidate,
    factor_items: list[dict[str, Any]],
    domain_facts: dict[str, list[dict[str, Any]]],
) -> str | None:
    """调用 LLM 做假设性深度分析。"""
    packet = candidate.packet
    tech = packet["technical"]
    fund = packet["fundamental"]
    evt = packet["event"]
    sec = packet["sector"]
    risk = packet["risk"]

    # 构建类似 build_decision_review_packet 的结构
    hypo_packet = {
        "target": {
            "type": "hypothetical_stock",
            "id": stock_code,
            "date": trading_date,
        },
        "hypothetical": True,
        "preopen_snapshot": {
            "candidate_packet": {
                "stock": packet["stock"],
                "technical": {"score": tech["score"], "momentum": tech["momentum"], "volume_surge": tech["volume_surge"], "trend_state": tech["trend_state"]},
                "fundamental": {"score": fund["score"], "available": fund.get("available")},
                "event": {"score": evt["score"], "available": evt.get("available"), "items": evt.get("items", [])},
                "sector": {"score": sec["score"], "available": sec.get("available")},
                "risk": {"score": risk["score"], "reasons": risk.get("reasons", [])},
                "data_coverage": packet.get("data_coverage", {}),
                "missing_fields": packet.get("missing_fields", []),
            },
            "pick_thesis": _build_hypothetical_thesis(packet),
        },
        "postclose_facts": {
            "intraday": {
                "note": "假设性复盘，无真实建仓和 outcome 数据",
            },
        },
        "deterministic_checks": [
            {"factor": fc["factor_type"], "verdict": fc["verdict"], "error": fc.get("error_type")}
            for fc in factor_items
        ],
        "domain_facts": domain_facts,
        "known_error_taxonomy": llm_prompt.KNOWN_ERROR_TAXONOMY,
        "allowed_outputs": {
            "max_attributions": 5,
            "must_cite_evidence_for_extracted": True,
            "optimization_signal_default_status": "candidate",
        },
    }

    system_prompt = (
        "You are a stock analysis assistant. Your role is to analyze a stock that was NOT "
        "selected by the trading strategy, but you are conducting a hypothetical post-market review. "
        "Evaluate the multi-factor signals (technical, fundamental, event, sector, risk) and "
        "provide an objective assessment of whether this stock would have been a good pick. "
        "Always cite evidence for EXTRACTED claims. Mark inferred claims as INFERRED. "
        "Return analysis in JSON format with attribution claims, reason checks, and a summary."
    )

    # 获取 LLM 配置
    config = _resolve_llm_config(conn)
    if config is None:
        return None

    if config.provider == "anthropic":
        return _call_anthropic(system_prompt, hypo_packet, config)
    elif config.provider == "openai":
        return _call_openai(system_prompt, hypo_packet, config)
    elif config.provider == "deepseek":
        return _call_deepseek(system_prompt, hypo_packet, config)
    return None


def _build_hypothetical_thesis(packet: dict[str, Any]) -> str:
    """构建假设性买入/卖出理由。"""
    tech = packet["technical"]
    fund = packet["fundamental"]
    evt = packet["event"]

    parts = []
    if tech["score"] > 0.1:
        parts.append(f"技术面评分 {tech['score']:.2f}，动量 {tech['momentum']:.2%}，趋势 {tech['trend_state']}")
    if fund.get("available") and fund["score"] > 0.4:
        parts.append(f"基本面良好，ROE {fund.get('roe', 'N/A')}，营收增长 {fund.get('revenue_growth', 'N/A')}")
    if evt.get("available") and evt["score"] > 0:
        items = evt.get("items", [])
        titles = [i.get("title", "") for i in items[:2]]
        parts.append(f"有积极事件驱动：{'；'.join(titles)}")

    if not parts:
        return "各项信号偏弱，不建议关注"
    return "；".join(parts)


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------


def _call_anthropic(system_prompt: str, hypo_packet: dict, config: Any) -> str | None:
    try:
        from anthropic import Anthropic  # type: ignore[import-untyped]
    except ImportError:
        return None

    client = Anthropic(api_key=config.api_key, base_url=config.base_url)
    response = client.messages.create(
        model=config.model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Analyze this hypothetical stock review:\n\n{hypo_packet}"}],
    )
    return response.content[0].text if response.content else None


def _call_openai(system_prompt: str, hypo_packet: dict, config: Any) -> str | None:
    try:
        from openai import OpenAI  # type: ignore[import-untyped]
    except ImportError:
        return None

    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    response = client.chat.completions.create(
        model=config.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analyze this hypothetical stock review:\n\n{hypo_packet}"},
        ],
        max_tokens=2048,
    )
    return response.choices[0].message.content if response.choices else None


def _call_deepseek(system_prompt: str, hypo_packet: dict, config: Any) -> str | None:
    try:
        from openai import OpenAI  # type: ignore[import-untyped]
    except ImportError:
        return None

    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    response = client.chat.completions.create(
        model=config.model or "deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analyze this hypothetical stock review:\n\n{hypo_packet}"},
        ],
        max_tokens=2048,
    )
    return response.choices[0].message.content if response.choices else None


# ---------------------------------------------------------------------------
# LLM Config 解析
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None = None


def _resolve_llm_config(conn: sqlite3.Connection) -> _LLMConfig | None:
    """从环境变量或配置表解析 LLM 配置。"""
    import os

    # 优先用环境变量
    if os.environ.get("DEEPSEEK_API_KEY"):
        return _LLMConfig(
            provider="deepseek",
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _LLMConfig(
            provider="anthropic",
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6-20250514"),
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )
    if os.environ.get("OPENAI_API_KEY"):
        return _LLMConfig(
            provider="openai",
            model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
            api_key=os.environ["OPENAI_API_KEY"],
        )

    # 尝试从配置表读取
    try:
        row = conn.execute("SELECT key, value FROM app_config WHERE key LIKE 'llm_%' LIMIT 10").fetchall()
    except Exception:
        return None  # app_config 表不存在
    if not row:
        return None

    config_map = {r["key"]: r["value"] for r in row}
    provider = config_map.get("llm_provider")
    api_key = config_map.get("llm_api_key")
    if not provider or not api_key:
        return None

    return _LLMConfig(
        provider=provider,
        model=config_map.get("llm_model", "gpt-4o"),
        api_key=api_key,
        base_url=config_map.get("llm_base_url"),
    )


# ---------------------------------------------------------------------------
# Gene 初始化
# ---------------------------------------------------------------------------


def _ensure_hypothetical_gene(conn: sqlite3.Connection) -> None:
    """确保 hypothetical gene 存在于 strategy_genes 表中。"""
    existing = conn.execute(
        "SELECT gene_id FROM strategy_genes WHERE gene_id = ?",
        (DEFAULT_GENE_ID,),
    ).fetchone()
    if existing:
        return

    # 使用与 champion gene 相同的默认参数
    default_params = {
        "max_picks": 5,
        "min_score": 0.005,
        "position_pct": 0.10,
        "take_profit_pct": 0.06,
        "stop_loss_pct": -0.035,
        "time_exit_days": 1,
        "technical_component_weight": 0.45,
        "fundamental_component_weight": 0.2,
        "event_component_weight": 0.2,
        "sector_component_weight": 0.15,
        "risk_component_weight": 0.3,
        "momentum_weight": 0.5,
        "volume_weight": 0.2,
        "volatility_weight": 0.05,
        "volatility_penalty": 0.1,
        "lookback_days": 6,
        "min_avg_amount": 0,
        "max_per_industry": 2,
    }

    conn.execute(
        """
        INSERT INTO strategy_genes (gene_id, name, params_json, status, horizon, risk_profile, created_at)
        VALUES (?, ?, ?, 'active', 'short', 'balanced', datetime('now'))
        """,
        (DEFAULT_GENE_ID, "假设性复盘", json.dumps(default_params)),
    )
    conn.commit()

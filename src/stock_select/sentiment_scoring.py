"""Short-term sentiment scoring for announcement alerts.

Combines capital flow, sector heat, chip structure, and shareholder
trend into a composite 0-1 sentiment score.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Weights for composite score (sum to 1.0)
WEIGHT_CAPITAL_FLOW = 0.30
WEIGHT_SECTOR_HEAT = 0.30
WEIGHT_CHIP_STRUCTURE = 0.20
WEIGHT_SHAREHOLDER_TREND = 0.20


@dataclass
class SentimentScore:
    stock_code: str
    trading_date: str
    capital_flow_score: float
    sector_heat_score: float
    chip_structure_score: float
    shareholder_trend_score: float
    composite: float
    opportunity_type: str  # breakout / sector_leader / event_driven


# ──────────────────────────────────────────────
# Capital flow sub-score
# ──────────────────────────────────────────────

def compute_capital_flow_score(
    conn, stock_code: str, trading_date: str
) -> tuple[float, str]:
    """Score 0-1 based on recent fund flow direction.

    Uses capital_flow_daily table if available, falls back to
    AkShare API for real-time data, then volume-price estimation.

    Returns (score, evidence_text).
    """
    # Try capital_flow_daily first
    rows = conn.execute(
        """SELECT main_net_inflow, large_order_inflow, super_large_inflow, retail_outflow
           FROM capital_flow_daily
           WHERE stock_code=? AND trading_date<=?
           ORDER BY trading_date DESC LIMIT 5""",
        (stock_code, trading_date),
    ).fetchall()

    if rows:
        total_ratio = 0.0
        count = 0
        for r in rows:
            main = r["main_net_inflow"] or 0
            large = r["large_order_inflow"] or 0
            super_lg = r["super_large_inflow"] or 0
            retail = r["retail_outflow"] or 0
            total_in = large + super_lg
            total_out = retail
            total = total_in + total_out
            if total > 0:
                net_ratio = (total_in - total_out) / total
                total_ratio += net_ratio
                count += 1

        if count > 0:
            avg_ratio = total_ratio / count
            score = (avg_ratio + 1.0) / 2.0
            net = sum((r["large_order_inflow"] or 0) + (r["super_large_inflow"] or 0) - (r["retail_outflow"] or 0) for r in rows)
            evidence = f"数据库近{count}日, 主力净{'流入' if net > 0 else '流出'}{abs(net)/1e4:.0f}万"
            return score, evidence

    # Fallback 1: AkShare real-time API
    try:
        from .capital_flow import _fetch_akshare_fund_flow, _classify_flow_trend
        ak_rows = _fetch_akshare_fund_flow(stock_code)
        if ak_rows and isinstance(ak_rows, list) and len(ak_rows) > 0:
            last = ak_rows[-1]
            # AkShare column names
            main = float(last.get("主力净流入-净额", 0) or 0)
            super_lg = float(last.get("超大单净流入-净额", 0) or 0)
            large = float(last.get("大单净流入-净额", 0) or 0)
            small = float(last.get("小单净流入-净额", 0) or 0)
            middle = float(last.get("中单净流入-净额", 0) or 0)
            # All AkShare columns are net values (positive=inflow, negative=outflow)
            # Normalize main flow against total absolute flow
            total_abs = abs(super_lg) + abs(large) + abs(small) + abs(middle)
            if total_abs > 0:
                net_ratio = main / total_abs  # range [-1, 1]
                score = (net_ratio + 1.0) / 2.0  # range [0, 1]
            else:
                score = 0.5
            trend = _classify_flow_trend(main, total_abs)
            evidence = f"AKShare实时, 主力净{'流入' if main > 0 else '流出'}{abs(main)/1e4:.0f}万({trend})"
            return score, evidence
    except Exception:
        pass  # API unavailable, continue to fallback

    # Fallback 2: estimate from price/volume
    prices = conn.execute(
        """SELECT close, volume
           FROM daily_prices
           WHERE stock_code=? AND trading_date<=?
           ORDER BY trading_date DESC LIMIT 10""",
        (stock_code, trading_date),
    ).fetchall()

    if len(prices) >= 3:
        up_days = 0
        total_volume = 0
        up_volume = 0
        for i in range(min(5, len(prices) - 1)):
            p0 = prices[i] if isinstance(prices[i], tuple) else prices[i]
            p1 = prices[i + 1] if isinstance(prices[i + 1], tuple) else prices[i + 1]
            c0 = p0[0] if isinstance(p0, tuple) else p0.get("close")
            c1 = p1[0] if isinstance(p1, tuple) else p1.get("close")
            v0 = p0[1] if isinstance(p0, tuple) else p0.get("volume") or 0
            if c0 and c1:
                if c0 > c1:
                    up_days += 1
                    up_volume += v0
                total_volume += v0

        if total_volume > 0:
            vol_ratio = up_volume / total_volume
            price_ratio = up_days / 5
            score = 0.6 * vol_ratio + 0.4 * price_ratio
            evidence = f"无资金数据, 量价估算: 近5日{up_days}日上涨"
            return score, evidence

    return 0.5, "无资金数据, 中性"


# ──────────────────────────────────────────────
# Sector heat sub-score
# ──────────────────────────────────────────────

def compute_sector_heat(conn, stock_code: str, trading_date: str) -> tuple[float, str]:
    """Score 0-1 based on sector momentum and theme alignment.
    Returns (score, evidence_text).
    """
    row = conn.execute(
        "SELECT industry FROM stocks WHERE stock_code=?",
        (stock_code,),
    ).fetchone()
    industry = row["industry"] if row and row["industry"] else None

    if not industry:
        return 0.5, "无行业信息"

    # Check sector_theme_signals
    theme_row = conn.execute(
        """SELECT theme_strength FROM sector_theme_signals
           WHERE industry=? AND trading_date<=?
           ORDER BY trading_date DESC LIMIT 1""",
        (industry, trading_date),
    ).fetchone()

    if theme_row and theme_row["theme_strength"]:
        score = min(1.0, max(0.0, float(theme_row["theme_strength"])))
        level = "热门" if score >= 0.7 else "温和" if score >= 0.4 else "冷清"
        return score, f"行业:{industry}, 题材强度{score:.2f}({level})"

    # Fallback: sector_heat_index
    heat_row = conn.execute(
        """SELECT heat_score FROM sector_heat_index
           WHERE industry=? AND trading_date<=?
           ORDER BY trading_date DESC LIMIT 1""",
        (industry, trading_date),
    ).fetchone()

    if heat_row:
        score = min(1.0, max(0.0, float(heat_row["heat_score"])))
        return score, f"行业:{industry}, 热度{score:.2f}"

    return 0.5, f"行业:{industry}, 无板块数据"


# ──────────────────────────────────────────────
# Chip structure sub-score
# ──────────────────────────────────────────────

def compute_chip_structure_score(
    conn, stock_code: str, trading_date: str
) -> tuple[float, str]:
    """Score 0-1 based on turnover, volume pattern, and price position.
    Returns (score, evidence_text).
    """
    prices = conn.execute(
        """SELECT close, volume
           FROM daily_prices
           WHERE stock_code=? AND trading_date<=?
           ORDER BY trading_date DESC LIMIT 20""",
        (stock_code, trading_date),
    ).fetchall()

    if len(prices) < 5:
        return 0.5, "数据不足"

    # Handle both Row objects and tuples
    closes = []
    volumes = []
    for p in prices:
        if isinstance(p, dict):
            c = p.get("close")
            v = p.get("volume")
        else:
            c = p[0]
            v = p[1]
        if c:
            closes.append(c)
        if v:
            volumes.append(v)

    if len(closes) < 3:
        return 0.5, "数据不足"

    # Price position
    high_20 = max(closes)
    low_20 = min(closes)
    price_range = high_20 - low_20
    if price_range > 0:
        price_position = (closes[0] - low_20) / price_range
    else:
        price_position = 0.5

    if 0.6 <= price_position <= 0.85:
        position_score = 1.0
    elif price_position > 0.85:
        position_score = 0.7
    else:
        position_score = price_position / 0.6 * 0.5

    # Volume trend (neutral if no volume data)
    has_volume = any(v > 0 for v in volumes)
    if has_volume and len(volumes) >= 5:
        recent_vol = sum(volumes[:5]) / 5
        prev_vol = sum(volumes[5:10]) / 5 if len(volumes) >= 10 else recent_vol
        vol_ratio = recent_vol / prev_vol if prev_vol > 0 else 1.0
        if 1.0 <= vol_ratio <= 2.0:
            vol_score = 1.0
        elif vol_ratio < 1.0:
            vol_score = vol_ratio
        else:
            vol_score = max(0.3, 2.0 - vol_ratio * 0.5)
        vol_label = "放量" if vol_ratio > 1.2 else "缩量" if vol_ratio < 0.8 else "平量"
        vol_evidence = f", {vol_label}(量比{vol_ratio:.2f})"
    else:
        vol_score = 0.5
        vol_evidence = ""

    score = 0.6 * position_score + 0.4 * vol_score
    pos_label = "近高位" if price_position >= 0.6 else "中位" if price_position >= 0.3 else "低位"
    evidence = f"20日{pos_label}({price_position:.0%}){vol_evidence}"
    return score, evidence


# ──────────────────────────────────────────────
# Shareholder trend sub-score
# ──────────────────────────────────────────────

def compute_shareholder_trend_score(
    conn, stock_code: str, trading_date: str
) -> tuple[float, str]:
    """Score 0-1 based on shareholder count trend.

    Tries the shareholder_data table first; falls back to a volume-price
    estimation (shrinking volume + rising price ≈ concentration).
    Returns (score, evidence_text).
    """
    try:
        rows = conn.execute(
            """SELECT shareholder_count, avg_holding
               FROM shareholder_data
               WHERE stock_code=? AND report_date<=?
               ORDER BY report_date DESC LIMIT 4""",
            (stock_code, trading_date),
        ).fetchall()
    except Exception:
        rows = []

    if len(rows) >= 2:
        counts = [r["shareholder_count"] for r in rows if r["shareholder_count"]]
        if len(counts) >= 2:
            decreasing = sum(1 for i in range(len(counts) - 1) if counts[i] < counts[i + 1])
            trend_ratio = decreasing / (len(counts) - 1)
            latest, oldest = counts[0], counts[-1]
            change_pct = (latest - oldest) / oldest * 100 if oldest > 0 else 0
            trend = "筹码集中" if change_pct < 0 else "筹码分散"
            evidence = f"股东{len(counts)}期, 变化{change_pct:+.1f}%({trend})"
            return trend_ratio, evidence

    # Fallback: estimate from price momentum (volume often unavailable)
    try:
        rows = conn.execute(
            """SELECT close FROM daily_prices
               WHERE stock_code=? AND trading_date<=?
               ORDER BY trading_date DESC LIMIT 10""",
            (stock_code, trading_date),
        ).fetchall()
    except Exception:
        return 0.5, "无股东数据"

    closes = [(r[0] if not isinstance(r, dict) else r["close"]) for r in rows if r and (r[0] if not isinstance(r, dict) else r["close"])]
    if len(closes) < 5:
        return 0.5, "量价数据不足"

    # Compare recent price action vs prior period for trend strength
    # Consistent uptrend suggests institutional accumulation
    recent_avg = sum(closes[:3]) / 3
    prior_avg = sum(closes[3:6]) / 3
    trend = (recent_avg - prior_avg) / prior_avg if prior_avg > 0 else 0

    # Volatility squeeze + rising price = accumulation
    recent_range = max(closes[:5]) - min(closes[:5])
    prior_range = max(closes[5:10]) - min(closes[5:10]) if len(closes) >= 10 else recent_range
    vol_squeeze = prior_range / recent_range if recent_range > 0 else 1.0

    if trend > 0.03 and vol_squeeze > 1.2:
        score = min(0.85, 0.6 + trend)
        label = "强势上涨, 筹码趋向集中"
    elif trend > 0.02:
        score = min(0.7, 0.55 + trend)
        label = "温和上涨, 趋势偏多"
    elif trend < -0.03:
        score = max(0.2, 0.5 + trend)
        label = "弱势下跌, 趋势偏空"
    else:
        score = 0.5
        label = "价格平稳, 中性"

    evidence = f"无股东数据, 量价估算: {label}"
    return score, evidence


# ──────────────────────────────────────────────
# Composite scorer
# ──────────────────────────────────────────────

def score_announcement_sentiment(
    conn,
    stock_code: str,
    trading_date: str,
    alert_type: str,
    base_confidence: float = 0.5,
) -> SentimentScore:
    """Compute full sentiment score for an alert."""
    capital, _ = compute_capital_flow_score(conn, stock_code, trading_date)
    sector, _ = compute_sector_heat(conn, stock_code, trading_date)
    chip, _ = compute_chip_structure_score(conn, stock_code, trading_date)
    shareholder, _ = compute_shareholder_trend_score(conn, stock_code, trading_date)

    composite = (
        capital * WEIGHT_CAPITAL_FLOW
        + sector * WEIGHT_SECTOR_HEAT
        + chip * WEIGHT_CHIP_STRUCTURE
        + shareholder * WEIGHT_SHAREHOLDER_TREND
    )

    # Alert type bonus
    type_bonus = {
        "earnings_beat": 0.05,
        "large_order": 0.05,
        "m_and_a": 0.08,
        "asset_injection": 0.06,
        "tech_breakthrough": 0.04,
    }
    composite = min(1.0, composite + type_bonus.get(alert_type, 0))

    # Determine opportunity type
    if sector >= 0.7 and capital >= 0.6:
        opportunity_type = "sector_leader"
    elif capital >= 0.7:
        opportunity_type = "breakout"
    else:
        opportunity_type = "event_driven"

    return SentimentScore(
        stock_code=stock_code,
        trading_date=trading_date,
        capital_flow_score=round(capital, 3),
        sector_heat_score=round(sector, 3),
        chip_structure_score=round(chip, 3),
        shareholder_trend_score=round(shareholder, 3),
        composite=round(composite, 3),
        opportunity_type=opportunity_type,
    )


# ──────────────────────────────────────────────
# Sector heat index refresh
# ──────────────────────────────────────────────

def refresh_sector_heat_index(conn, trading_date: str) -> None:
    """Compute and cache sector heat scores for the given date."""
    # Get all sectors with their theme signals
    sectors = conn.execute(
        """SELECT DISTINCT industry FROM stocks WHERE industry IS NOT NULL"""
    ).fetchall()

    for s in sectors:
        industry = s["industry"]

        # Count stocks in sector
        stock_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM stocks WHERE industry=?",
            (industry,),
        ).fetchone()["cnt"]

        # Count limit-up stocks (price change >= 9.5%)
        limit_up = conn.execute(
            """SELECT COUNT(DISTINCT dp.stock_code) as cnt
               FROM daily_prices dp
               JOIN stocks s ON dp.stock_code = s.stock_code
               WHERE s.industry=? AND dp.trading_date=?
               AND dp.prev_close IS NOT NULL AND dp.prev_close > 0
               AND (dp.close - dp.prev_close) / dp.prev_close >= 0.095""",
            (industry, trading_date),
        ).fetchone()["cnt"]

        # Get theme strength
        theme_row = conn.execute(
            """SELECT theme_strength FROM sector_theme_signals
               WHERE industry=? AND trading_date<=?
               ORDER BY trading_date DESC LIMIT 1""",
            (industry, trading_date),
        ).fetchone()

        theme_score = 0.5
        if theme_row and theme_row["theme_strength"]:
            theme_score = float(theme_row["theme_strength"])

        # Limit-up bonus
        if stock_count > 0:
            limit_up_ratio = limit_up / stock_count
            heat = min(1.0, theme_score * 0.6 + limit_up_ratio * 0.4)
        else:
            heat = theme_score * 0.6

        conn.execute(
            """INSERT OR REPLACE INTO sector_heat_index
               (trading_date, industry, heat_score, stock_count,
                limit_up_count, computed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trading_date, industry, round(heat, 3), stock_count,
             limit_up, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )

    conn.commit()

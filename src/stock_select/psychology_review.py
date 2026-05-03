from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


PSYCHOLOGICAL_MAP: dict[str, tuple[str, str]] = {
    "overweighted_technical": ("技术误判", "过度依赖技术指标，忽略了其他维度信号"),
    "underweighted_technical": ("技术误判", "技术面信号未被充分重视"),
    "underweighted_fundamental": ("消息遗漏", "基本面数据未被充分纳入决策"),
    "overweighted_fundamental": ("计划不周", "过度依赖基本面，忽略了市场风格切换"),
    "false_catalyst": ("计划不周", "催化逻辑不够硬，预期过于乐观"),
    "underweighted_sector": ("消息遗漏", "行业板块信号被忽略"),
    "sector_rotation_missed": ("消息遗漏", "未能及时识别板块轮动"),
    "risk_underestimated": ("情绪驱动", "低估风险，追高买入"),
    "risk_overestimated": ("情绪驱动", "过度恐惧，错失机会"),
    "liquidity_ignored": ("执行偏差", "忽略了流动性风险"),
    "entry_too_chasing": ("情绪驱动", "追高买入，缺乏耐心"),
    "sell_rule_too_tight": ("执行偏差", "卖出规则过于僵化，过早止盈"),
    "sell_rule_too_loose": ("执行偏差", "卖出规则过于宽松，未及时止损"),
    "position_too_large": ("情绪驱动", "仓位过重，贪婪心理"),
    "position_too_small": ("情绪驱动", "仓位过轻，恐惧心理"),
    "missed_earnings_surprise": ("消息遗漏", "忽略了业绩超预期信号"),
    "missed_order_signal": ("消息遗漏", "忽略了订单/合同利好信号"),
    "missed_business_kpi_signal": ("消息遗漏", "忽略了经营数据利好信号"),
    "missed_risk_event": ("消息遗漏", "忽略了风险事件信号"),
    "analyst_expectation_missing": ("消息遗漏", "分析师预期数据缺失"),
    "financial_actual_missing": ("消息遗漏", "实际财务数据缺失"),
    "data_missing": ("计划不周", "关键数据缺失，决策依据不足"),
    "data_stale": ("计划不周", "使用了过期的数据"),
    "thesis_not_specific": ("计划不周", "投资逻辑不够具体"),
    "thesis_contradicted_by_data": ("技术误判", "投资逻辑与数据矛盾"),
    "missing_counterargument": ("计划不周", "缺少反面论证"),
    "threshold_too_strict": ("执行偏差", "阈值设置过严，过滤了潜在机会"),
    "threshold_too_loose": ("执行偏差", "阈值设置过松，纳入了劣质标的"),
    "hard_filter_too_strict": ("执行偏差", "硬性过滤条件过严"),
    "candidate_not_recalled": ("技术误判", "候选股票未被正确召回"),
    "diversity_rerank_missed": ("计划不周", "多样性重排序导致错失优质标的"),
    "entry_unfillable": ("执行偏差", "开盘价无法成交"),
    "time_exit_mismatch": ("执行偏差", "时间退出策略不匹配"),
    "late_signal": ("消息遗漏", "信号发出过晚，错过最佳时机"),
    "source_conflict": ("技术误判", "数据源之间存在冲突"),
    "bad_snapshot": ("技术误判", "快照数据异常"),
    "evidence_as_of_date_invalid": ("技术误判", "证据日期无效"),
    "event_visibility_invalid": ("技术误判", "事件可见性判断错误"),
    "low_evidence_coverage": ("计划不周", "证据覆盖不足"),
    "llm_over_inferred": ("技术误判", "LLM 过度推断"),
    "ambiguous_attribution": ("技术误判", "归因模糊"),
    "overtrusted_framework_order": ("执行偏差", "过度信任框架排名"),
    "missed_guidance_revision": ("消息遗漏", "忽略了业绩指引修正"),
    "false_earnings_surprise": ("技术误判", "错误识别了业绩超预期"),
    "sector_weak_but_stock_picked": ("情绪驱动", "板块弱势但逆势选股"),
}


@dataclass(frozen=True)
class PsychologicalAttribution:
    category: str
    description: str
    error_types: list[str]
    prevention: str


@dataclass(frozen=True)
class PsychologyReview:
    decision_review_id: str
    success_reasons: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    psychological_category: str = ""
    reproducible_patterns: list[str] = field(default_factory=list)
    prevention_strategies: list[str] = field(default_factory=list)


def _fetch_errors(conn: sqlite3.Connection, decision_review_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT error_type, severity, confidence
        FROM review_errors
        WHERE review_id = ? AND review_scope = 'decision'
        ORDER BY severity DESC
        """,
        (decision_review_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_verdict(conn: sqlite3.Connection, decision_review_id: str) -> str:
    row = conn.execute(
        "SELECT verdict, return_pct FROM decision_reviews WHERE review_id = ?",
        (decision_review_id,),
    ).fetchone()
    if row is None:
        return "NEUTRAL"
    return row["verdict"]


def _categorize_errors(error_types: list[str]) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}
    for et in error_types:
        cat, desc = PSYCHOLOGICAL_MAP.get(et, ("未分类", "未知错误类型"))
        categories.setdefault(cat, []).append(desc)
    return categories


def build_psychology_review(
    conn: sqlite3.Connection, decision_review_id: str
) -> PsychologyReview:
    verdict = _fetch_verdict(conn, decision_review_id)
    errors = _fetch_errors(conn, decision_review_id)
    error_types = [e["error_type"] for e in errors]

    categories = _categorize_errors(error_types)

    if verdict == "RIGHT":
        psychological_category = "执行到位"
        success_reasons = [
            "决策逻辑与盘面走势一致",
            "关键因素被正确识别并纳入评分",
        ]
        failure_reasons = []
        reproducible = [
            "在类似市场环境下重复该选股逻辑",
            "保持当前因子权重配置",
        ]
        prevention = [
            "记录成功模式，建立案例库",
            "定期回顾类似市场环境下的表现",
        ]
    elif verdict == "WRONG":
        top_cat = next(iter(categories), "未分类")
        psychological_category = top_cat
        success_reasons = []
        failure_reasons = [f"{cat}: {', '.join(descs[:2])}" for cat, descs in categories.items()]
        reproducible = []
        prevention = [
            f"针对'{top_cat}'类错误建立检查清单",
            "增加反面论证环节",
            "设置硬性止损规则",
        ]
    else:
        psychological_category = "mixed"
        success_reasons = ["部分判断正确"]
        failure_reasons = [f"{cat}: {', '.join(descs[:2])}" for cat, descs in categories.items() if cat != "执行到位"]
        reproducible = ["分离正确与错误的归因因子"]
        prevention = ["加强多因子交叉验证"]

    return PsychologyReview(
        decision_review_id=decision_review_id,
        success_reasons=success_reasons,
        failure_reasons=failure_reasons,
        psychological_category=psychological_category,
        reproducible_patterns=reproducible,
        prevention_strategies=prevention,
    )


def save_psychology_review(conn: sqlite3.Connection, review: PsychologyReview) -> None:
    conn.execute(
        """
        INSERT INTO psychology_review (
            decision_review_id, success_reasons, failure_reasons,
            psychological_category, reproducible_patterns, prevention_strategies
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(decision_review_id) DO UPDATE SET
            success_reasons = excluded.success_reasons,
            failure_reasons = excluded.failure_reasons,
            psychological_category = excluded.psychological_category,
            reproducible_patterns = excluded.reproducible_patterns,
            prevention_strategies = excluded.prevention_strategies,
            created_at = datetime('now')
        """,
        (
            review.decision_review_id,
            json.dumps(review.success_reasons),
            json.dumps(review.failure_reasons),
            review.psychological_category,
            json.dumps(review.reproducible_patterns),
            json.dumps(review.prevention_strategies),
        ),
    )
    conn.commit()


def get_psychology_review(
    conn: sqlite3.Connection, decision_review_id: str
) -> PsychologyReview | None:
    row = conn.execute(
        "SELECT * FROM psychology_review WHERE decision_review_id = ?",
        (decision_review_id,),
    ).fetchone()
    if row is None:
        return None
    return PsychologyReview(
        decision_review_id=row["decision_review_id"],
        success_reasons=json.loads(row["success_reasons"] or "[]"),
        failure_reasons=json.loads(row["failure_reasons"] or "[]"),
        psychological_category=row["psychological_category"] or "",
        reproducible_patterns=json.loads(row["reproducible_patterns"] or "[]"),
        prevention_strategies=json.loads(row["prevention_strategies"] or "[]"),
    )


def generate_psychology_review(
    conn: sqlite3.Connection, decision_review_id: str
) -> PsychologyReview:
    review = build_psychology_review(conn, decision_review_id)
    save_psychology_review(conn, review)
    return review

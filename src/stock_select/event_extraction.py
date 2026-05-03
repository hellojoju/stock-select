"""Deterministic event classification from announcement/news titles."""
from __future__ import annotations

import re

# Event type patterns: (type_name, regex_patterns)
_EVENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("重大合同", [r"合同", r"中标", r"订单", r"协议"]),
    ("业绩预告", [r"业绩", r"预增", r"预减", r"扭亏", r"首亏", r"续亏", r"略增", r"略减"]),
    ("财报发布", [r"年报", r"中报", r"季报", r"三季报", r"一季报", r"财报", r"财务报告"]),
    ("监管问询", [r"问询", r"关注函", r"监管", r"立案调查", r"处罚"]),
    ("股权变动", [r"增持", r"减持", r"股权转让", r"股东变更", r"股份回购"]),
    ("停复牌", [r"停牌", r"复牌", r"退市风险", r"摘牌"]),
    ("分红配股", [r"分红", r"派息", r"配股", r"送股", r"转增"]),
    ("诉讼仲裁", [r"诉讼", r"仲裁", r"纠纷"]),
    ("政策利好", [r"政策", r"利好", r"扶持", r"补贴", r"规划"]),
    ("风险事件", [r"风险", r"违规", r"违约", r"担保", r"质押", r"冻结"]),
    ("资产重组", [r"重组", r"并购", r"收购", r"资产注入"]),
    ("人事变动", [r"董事", r"监事", r"高管", r"辞职", r"任命"]),
]


def classify_event(title: str, summary: str | None = None) -> tuple[str, float]:
    """Classify an event from its title/summary. Returns (event_type, confidence)."""
    text = f"{title} {(summary or '')}"
    scores: dict[str, int] = {}
    for event_type, patterns in _EVENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text):
                scores[event_type] = scores.get(event_type, 0) + 1

    if not scores:
        return ("一般资讯", 0.5)

    best_type = max(scores, key=scores.get)
    match_count = scores[best_type]
    # Confidence based on number of matched patterns
    confidence = min(0.95, 0.6 + match_count * 0.1)
    return (best_type, confidence)

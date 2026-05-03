from __future__ import annotations

import hashlib
import json
import sqlite3
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from . import repository
from .data_quality import compare_and_publish_prices


DEFAULT_INDEX_CODES = ["000300.SH", "000001.SH", "399006.SZ"]
DEFAULT_FACTOR_STOCK_LIMIT = 500


class UnsupportedDatasetError(RuntimeError):
    pass


@dataclass(frozen=True)
class StockUniverseItem:
    stock_code: str
    name: str
    exchange: str | None = None
    industry: str | None = None
    list_date: str | None = None
    is_active: bool = True
    is_st: bool = False


@dataclass(frozen=True)
class TradingCalendarItem:
    trading_date: str
    is_open: bool
    source: str


@dataclass(frozen=True)
class SourcePrice:
    source: str
    stock_code: str
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0
    is_suspended: bool = False
    is_limit_up: bool = False
    is_limit_down: bool = False


@dataclass(frozen=True)
class SourceIndexPrice:
    source: str
    index_code: str
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0


@dataclass(frozen=True)
class IndustryItem:
    source: str
    stock_code: str
    industry: str
    as_of_date: str


@dataclass(frozen=True)
class SectorSignalItem:
    source: str
    trading_date: str
    industry: str
    sector_return_pct: float
    relative_strength_rank: int
    volume_surge: float = 0.0
    theme_strength: float = 0.0
    catalyst_count: int = 0
    summary: str = ""


@dataclass(frozen=True)
class FundamentalMetricItem:
    source: str
    stock_code: str
    as_of_date: str
    report_period: str
    roe: float | None = None
    revenue_growth: float | None = None
    net_profit_growth: float | None = None
    gross_margin: float | None = None
    debt_to_assets: float | None = None
    operating_cashflow_to_profit: float | None = None
    pe_percentile: float | None = None
    pb_percentile: float | None = None
    dividend_yield: float | None = None
    quality_note: str | None = None


@dataclass(frozen=True)
class EventSignalItem:
    source: str
    event_id: str
    trading_date: str
    published_at: str
    event_type: str
    title: str
    summary: str
    stock_code: str | None = None
    industry: str | None = None
    impact_score: float = 0.0
    sentiment: float = 0.0


@dataclass(frozen=True)
class FinancialActualItem:
    source: str
    stock_code: str
    report_period: str
    publish_date: str
    as_of_date: str
    revenue: float | None = None
    net_profit: float | None = None
    deducted_net_profit: float | None = None
    eps: float | None = None
    roe: float | None = None
    gross_margin: float | None = None
    operating_cashflow: float | None = None
    debt_to_assets: float | None = None
    source_url: str | None = None
    source_fetched_at: str | None = None
    confidence: float = 1.0
    raw_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class AnalystExpectationItem:
    source: str
    stock_code: str
    report_date: str
    forecast_period: str
    org_name: str | None = None
    author_name: str | None = None
    report_title: str | None = None
    forecast_revenue: float | None = None
    forecast_net_profit: float | None = None
    forecast_eps: float | None = None
    forecast_pe: float | None = None
    rating: str | None = None
    target_price_min: float | None = None
    target_price_max: float | None = None
    source_url: str | None = None
    source_fetched_at: str | None = None
    confidence: float = 1.0
    raw_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class OrderContractEventItem:
    source: str
    stock_code: str
    publish_date: str
    event_type: str
    title: str
    as_of_date: str | None = None
    event_date: str | None = None
    summary: str | None = None
    contract_amount: float | None = None
    contract_amount_pct_revenue: float | None = None
    counterparty: str | None = None
    duration: str | None = None
    impact_score: float = 0.0
    source_url: str | None = None
    source_fetched_at: str | None = None
    confidence: float = 1.0
    raw_json: dict[str, Any] | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class BusinessKpiItem:
    source: str
    stock_code: str
    report_period: str
    kpi_name: str
    kpi_value: float
    kpi_unit: str
    publish_date: str | None = None
    as_of_date: str | None = None
    kpi_yoy: float | None = None
    kpi_qoq: float | None = None
    industry: str | None = None
    source_url: str | None = None
    source_fetched_at: str | None = None
    confidence: float = 1.0
    raw_json: dict[str, Any] | None = None
    kpi_id: str | None = None


@dataclass(frozen=True)
class RiskEventItem:
    source: str
    stock_code: str
    event_date: str
    publish_date: str
    as_of_date: str
    risk_type: str
    title: str
    severity: str = "medium"
    summary: str | None = None
    impact_score: float = 0.0
    source_url: str | None = None
    source_fetched_at: str | None = None
    confidence: float = 1.0
    raw_json: dict[str, Any] | None = None
    risk_event_id: str | None = None


class MarketDataProvider(Protocol):
    source: str

    def fetch_stock_universe(self) -> list[StockUniverseItem]:
        ...

    def fetch_trading_calendar(self, start: str, end: str) -> list[TradingCalendarItem]:
        ...

    def fetch_daily_prices(self, trading_date: str, stock_codes: list[str]) -> list[SourcePrice]:
        ...

    def fetch_index_prices(self, trading_date: str, index_codes: list[str]) -> list[SourceIndexPrice]:
        ...

    def fetch_industries(self, trading_date: str, stock_codes: list[str]) -> list[IndustryItem]:
        ...

    def fetch_fundamentals(self, trading_date: str, stock_codes: list[str]) -> list[FundamentalMetricItem]:
        ...

    def fetch_event_signals(self, start: str, end: str, stock_codes: list[str]) -> list[EventSignalItem]:
        ...

    def fetch_financial_actuals(self, trading_date: str, stock_codes: list[str]) -> list[FinancialActualItem]:
        ...

    def fetch_analyst_expectations(self, trading_date: str, stock_codes: list[str]) -> list[AnalystExpectationItem]:
        ...

    def fetch_order_contract_events(self, start: str, end: str, stock_codes: list[str]) -> list[OrderContractEventItem]:
        ...

    def fetch_business_kpis(self, trading_date: str, stock_codes: list[str]) -> list[BusinessKpiItem]:
        ...

    def fetch_risk_events(self, start: str, end: str, stock_codes: list[str]) -> list[RiskEventItem]:
        ...


class DemoProvider:
    """Deterministic local provider used for tests and offline demos."""

    source: str

    def __init__(self, source: str = "akshare", close_adjustment: float = 0.0) -> None:
        self.source = source
        self.close_adjustment = close_adjustment

    def fetch_stock_universe(self) -> list[StockUniverseItem]:
        return [
            StockUniverseItem("000001.SZ", "Ping An Bank", "SZSE", "Bank", "1991-04-03"),
            StockUniverseItem("000002.SZ", "Vanke A", "SZSE", "Real Estate", "1991-01-29"),
            StockUniverseItem("600519.SH", "Kweichow Moutai", "SSE", "Food", "2001-08-27"),
            StockUniverseItem("300750.SZ", "CATL", "SZSE", "Battery", "2018-06-11"),
        ]

    def fetch_trading_calendar(self, start: str, end: str) -> list[TradingCalendarItem]:
        start_date = parse_date(start)
        end_date = parse_date(end)
        days = []
        current = start_date
        while current <= end_date:
            days.append(TradingCalendarItem(current.isoformat(), current.weekday() < 5, self.source))
            current += timedelta(days=1)
        return days

    def fetch_daily_prices(self, trading_date: str, stock_codes: list[str]) -> list[SourcePrice]:
        prices: list[SourcePrice] = []
        for index, stock_code in enumerate(stock_codes):
            base = 10 + index * 3 + int(trading_date[-2:]) * 0.05
            close = base * (1 + self.close_adjustment)
            prices.append(
                SourcePrice(
                    source=self.source,
                    stock_code=stock_code,
                    trading_date=trading_date,
                    open=base * 0.99,
                    high=close * 1.02,
                    low=base * 0.97,
                    close=close,
                    volume=1_000_000 + index * 50_000,
                    amount=close * (1_000_000 + index * 50_000),
                )
            )
        return prices

    def fetch_daily_prices_range(self, start: str, end: str, stock_codes: list[str]) -> list[SourcePrice]:
        rows: list[SourcePrice] = []
        current = parse_date(start)
        end_date = parse_date(end)
        while current <= end_date:
            if current.weekday() < 5:
                rows.extend(self.fetch_daily_prices(current.isoformat(), stock_codes))
            current += timedelta(days=1)
        return rows

    def fetch_index_prices(self, trading_date: str, index_codes: list[str]) -> list[SourceIndexPrice]:
        rows: list[SourceIndexPrice] = []
        for index, index_code in enumerate(index_codes):
            base = 3000 + index * 500 + int(trading_date[-2:]) * 2
            close = base * (1 + self.close_adjustment)
            rows.append(
                SourceIndexPrice(
                    source=self.source,
                    index_code=index_code,
                    trading_date=trading_date,
                    open=base * 0.995,
                    high=close * 1.01,
                    low=base * 0.99,
                    close=close,
                    volume=10_000_000,
                    amount=close * 10_000_000,
                )
            )
        return rows

    def fetch_industries(self, trading_date: str, stock_codes: list[str]) -> list[IndustryItem]:
        industries = {item.stock_code: item.industry or "Unknown" for item in self.fetch_stock_universe()}
        return [
            IndustryItem(self.source, stock_code, industries.get(stock_code, "Unknown"), trading_date)
            for stock_code in stock_codes
        ]

    def fetch_fundamentals(self, trading_date: str, stock_codes: list[str]) -> list[FundamentalMetricItem]:
        as_of_date = (parse_date(trading_date) - timedelta(days=30)).isoformat()
        report_period = f"{parse_date(trading_date).year - 1}-12-31"
        rows: list[FundamentalMetricItem] = []
        for index, stock_code in enumerate(stock_codes):
            rows.append(
                FundamentalMetricItem(
                    source=self.source,
                    stock_code=stock_code,
                    as_of_date=as_of_date,
                    report_period=report_period,
                    roe=0.08 + index * 0.01,
                    revenue_growth=0.05 + index * 0.01,
                    net_profit_growth=0.04 + index * 0.01,
                    gross_margin=0.25,
                    debt_to_assets=0.45,
                    operating_cashflow_to_profit=1.0,
                    pe_percentile=0.45,
                    quality_note="demo fundamentals",
                )
            )
        return rows

    def fetch_event_signals(self, start: str, end: str, stock_codes: list[str]) -> list[EventSignalItem]:
        if not stock_codes:
            return []
        event_date = start
        return [
            EventSignalItem(
                source=self.source,
                event_id=event_signal_id(self.source, event_date, stock_codes[0], "demo_order", "demo positive order"),
                trading_date=event_date,
                published_at=event_date,
                stock_code=stock_codes[0],
                event_type="major_contract",
                title="demo positive order",
                summary="demo positive order",
                impact_score=0.45,
                sentiment=0.4,
            )
        ]

    def fetch_financial_actuals(self, trading_date: str, stock_codes: list[str]) -> list[FinancialActualItem]:
        report_period = f"{parse_date(trading_date).year - 1}-12-31"
        publish_date = (parse_date(trading_date) - timedelta(days=20)).isoformat()
        return [
            FinancialActualItem(
                source=self.source,
                stock_code=stock_code,
                report_period=report_period,
                publish_date=publish_date,
                as_of_date=publish_date,
                revenue=1_000_000_000 + index * 100_000_000,
                net_profit=100_000_000 + index * 10_000_000,
                deducted_net_profit=90_000_000 + index * 10_000_000,
                eps=0.5 + index * 0.1,
                roe=0.08 + index * 0.01,
                gross_margin=0.25,
                operating_cashflow=120_000_000 + index * 10_000_000,
                debt_to_assets=0.45,
                raw_json={"provider": "demo"},
            )
            for index, stock_code in enumerate(stock_codes)
        ]

    def fetch_analyst_expectations(self, trading_date: str, stock_codes: list[str]) -> list[AnalystExpectationItem]:
        report_date = (parse_date(trading_date) - timedelta(days=25)).isoformat()
        forecast_period = f"{parse_date(trading_date).year - 1}-12-31"
        return [
            AnalystExpectationItem(
                source=self.source,
                stock_code=stock_code,
                report_date=report_date,
                forecast_period=forecast_period,
                org_name="Demo Securities",
                author_name="Demo Analyst",
                forecast_revenue=900_000_000 + index * 100_000_000,
                forecast_net_profit=80_000_000 + index * 10_000_000,
                forecast_eps=0.4 + index * 0.1,
                rating="BUY",
                raw_json={"provider": "demo"},
            )
            for index, stock_code in enumerate(stock_codes)
        ]

    def fetch_order_contract_events(self, start: str, end: str, stock_codes: list[str]) -> list[OrderContractEventItem]:
        if not stock_codes:
            return []
        return [
            OrderContractEventItem(
                source=self.source,
                stock_code=stock_codes[0],
                publish_date=start,
                as_of_date=start,
                event_type="major_contract",
                title="demo positive order",
                summary="demo positive order",
                impact_score=0.45,
                raw_json={"provider": "demo"},
            )
        ]

    def fetch_business_kpis(self, trading_date: str, stock_codes: list[str]) -> list[BusinessKpiItem]:
        report_period = f"{parse_date(trading_date).year - 1}-12-31"
        publish_date = (parse_date(trading_date) - timedelta(days=20)).isoformat()
        return [
            BusinessKpiItem(
                source=self.source,
                stock_code=stock_code,
                report_period=report_period,
                publish_date=publish_date,
                as_of_date=publish_date,
                kpi_name="orders",
                kpi_value=100_000_000 + index * 10_000_000,
                kpi_unit="CNY",
                kpi_yoy=0.2,
                raw_json={"provider": "demo"},
            )
            for index, stock_code in enumerate(stock_codes[:2])
        ]

    def fetch_risk_events(self, start: str, end: str, stock_codes: list[str]) -> list[RiskEventItem]:
        if len(stock_codes) < 2:
            return []
        return [
            RiskEventItem(
                source=self.source,
                stock_code=stock_codes[1],
                event_date=start,
                publish_date=start,
                as_of_date=start,
                risk_type="shareholder_reduction",
                title="demo shareholder reduction",
                severity="medium",
                impact_score=-0.35,
                raw_json={"provider": "demo"},
            )
        ]


class AkShareProvider:
    source = "akshare"

    def fetch_stock_universe(self) -> list[StockUniverseItem]:
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare is not installed") from exc

        frame = ak.stock_info_a_code_name()
        rows: list[StockUniverseItem] = []
        for _, item in frame.iterrows():
            raw_code = str(value_from(item, "code", "代码", "证券代码"))
            name = str(value_from(item, "name", "名称", "证券简称") or raw_code)
            stock_code = normalize_stock_code(raw_code)
            if not stock_code:
                continue
            rows.append(
                StockUniverseItem(
                    stock_code=stock_code,
                    name=name,
                    exchange=exchange_for_code(stock_code),
                    is_active=True,
                    is_st=is_st_name(name),
                )
            )
        return rows

    def fetch_trading_calendar(self, start: str, end: str) -> list[TradingCalendarItem]:
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare is not installed") from exc

        frame = ak.tool_trade_date_hist_sina()
        rows: list[TradingCalendarItem] = []
        for _, item in frame.iterrows():
            raw = value_from(item, "trade_date", "交易日", "date")
            if raw is None:
                continue
            trading_date = normalize_date(raw)
            if start <= trading_date <= end:
                rows.append(TradingCalendarItem(trading_date, True, self.source))
        return rows

    def fetch_daily_prices(self, trading_date: str, stock_codes: list[str]) -> list[SourcePrice]:
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare is not installed") from exc

        date_token = trading_date.replace("-", "")

        def _fetch_one(code: str) -> SourcePrice | None:
            suffix = code.split(".")[-1]
            tx_prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(suffix, "sh")
            symbol = f"{tx_prefix}{code.split('.')[0]}"
            try:
                frame = ak.stock_zh_a_hist_tx(symbol=symbol, start_date=date_token, end_date=date_token)
            except Exception:
                return None
            if frame.empty:
                return None
            item = frame.iloc[0]
            return SourcePrice(
                source=self.source,
                stock_code=code,
                trading_date=trading_date,
                open=float(value_from(item, "开盘", "open")),
                high=float(value_from(item, "最高", "high")),
                low=float(value_from(item, "最低", "low")),
                close=float(value_from(item, "收盘", "close")),
                volume=0.0,
                amount=float(value_from(item, "成交额", "amount") or 0),
            )

        rows: list[SourcePrice] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            for result in pool.map(_fetch_one, stock_codes):
                if result is not None:
                    rows.append(result)
        return rows

    def fetch_index_prices(self, trading_date: str, index_codes: list[str]) -> list[SourceIndexPrice]:
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare is not installed") from exc

        rows: list[SourceIndexPrice] = []
        for index_code in index_codes:
            symbol = to_akshare_index_code(index_code)
            try:
                frame = ak.stock_zh_a_hist_tx(symbol=symbol)
            except Exception:
                continue
            if frame.empty:
                continue
            date_column = "date" if "date" in frame.columns else "日期"
            subset = frame[frame[date_column].astype(str).str[:10] == trading_date]
            if subset.empty:
                continue
            item = subset.iloc[0]
            rows.append(
                SourceIndexPrice(
                    source=self.source,
                    index_code=index_code,
                    trading_date=trading_date,
                    open=float(value_from(item, "open", "开盘")),
                    high=float(value_from(item, "high", "最高")),
                    low=float(value_from(item, "low", "最低")),
                    close=float(value_from(item, "close", "收盘")),
                    volume=0.0,
                    amount=float(value_from(item, "amount", "成交额") or 0),
                )
            )
        return rows

    def fetch_industries(self, trading_date: str, stock_codes: list[str]) -> list[IndustryItem]:
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare is not installed") from exc

        wanted = set(stock_codes)
        rows: list[IndustryItem] = []
        board_frame = ak.stock_board_industry_name_em()
        industry_names = [str(value_from(item, "板块名称", "名称", "name")) for _, item in board_frame.iterrows()]
        for industry in industry_names:
            if not industry or industry == "None":
                continue
            cons = ak.stock_board_industry_cons_em(symbol=industry)
            for _, item in cons.iterrows():
                stock_code = normalize_stock_code(str(value_from(item, "代码", "code", "证券代码") or ""))
                if stock_code and stock_code in wanted:
                    rows.append(IndustryItem(self.source, stock_code, industry, trading_date))
        return rows

    def fetch_fundamentals(self, trading_date: str, stock_codes: list[str]) -> list[FundamentalMetricItem]:
        """S5.3: Fetch basic fundamentals from AKShare (valuation, PE, PB)."""
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise UnsupportedDatasetError("akshare fundamentals require akshare package") from exc

        import pandas as pd  # type: ignore[import-not-found]

        rows: list[FundamentalMetricItem] = []
        captured = datetime.now(tz=__import__('datetime', fromlist=['timezone']).timezone.utc).isoformat()
        for stock_code in stock_codes:
            try:
                # AKShare stock individual info
                ak_code = stock_code
                info = ak.stock_individual_info_em(symbol=ak_code)
                if not isinstance(info, pd.DataFrame) or info.empty:
                    continue
                info_dict = dict(zip(info["item"], info["value"]))
                rows.append(FundamentalMetricItem(
                    source=self.source,
                    stock_code=stock_code,
                    as_of_date=trading_date,
                    report_period=trading_date,
                    pe_percentile=safe_float(info_dict.get("市盈率")),
                    quality_note="akshare stock_individual_info_em: " + json.dumps(
                        {k: str(v) for k, v in info_dict.items()},
                        ensure_ascii=False,
                    )[:500],
                ))
            except Exception:
                continue  # Skip individual stock failures

        return rows

    def fetch_event_signals(self, start: str, end: str, stock_codes: list[str]) -> list[EventSignalItem]:
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare is not installed") from exc

        wanted = set(stock_codes)
        rows: list[EventSignalItem] = []
        current = parse_date(start)
        end_date = parse_date(end)
        while current <= end_date:
            date_token = current.strftime("%Y%m%d")
            frame = ak.stock_notice_report(symbol="全部", date=date_token)
            for _, item in frame.iterrows():
                stock_code = normalize_stock_code(str(value_from(item, "代码", "code", "证券代码") or ""))
                if not stock_code or stock_code not in wanted:
                    continue
                title = str(value_from(item, "公告标题", "title") or "")
                event_type, impact, sentiment = classify_event_title(title)
                published_at = normalize_date(value_from(item, "公告日期", "date") or current.isoformat())
                rows.append(
                    EventSignalItem(
                        source=self.source,
                        event_id=event_signal_id(self.source, published_at, stock_code, event_type, title),
                        trading_date=published_at,
                        published_at=published_at,
                        stock_code=stock_code,
                        event_type=event_type,
                        title=title,
                        summary=title,
                        impact_score=impact,
                        sentiment=sentiment,
                    )
                )
            current += timedelta(days=1)
        return rows

    def fetch_financial_actuals(self, trading_date: str, stock_codes: list[str]) -> list[FinancialActualItem]:
        raise UnsupportedDatasetError("akshare financial_actuals are not configured; use baostock")

    def fetch_analyst_expectations(self, trading_date: str, stock_codes: list[str]) -> list[AnalystExpectationItem]:
        """Fetch analyst profit forecasts and ratings from EastMoney via AKShare."""
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare is not installed") from exc

        rows: list[AnalystExpectationItem] = []
        for stock_code in stock_codes:
            try:
                frame = ak.stock_research_report_em(symbol=stock_code)
            except Exception:
                continue
            if frame is None or frame.empty:
                continue
            for _, item in frame.iterrows():
                report_date = normalize_date(value_from(item, "日期", "report_date", "发布日期"))
                if not report_date:
                    continue
                title = str(value_from(item, "报告名称", "title") or "")
                rating = str(value_from(item, "东财评级", "rating") or "") or None
                org_name = str(value_from(item, "机构", "org_name", "研究机构") or "") or None
                pdf_link = str(value_from(item, "报告PDF链接", "pdf_url", "pdf_link") or "") or None

                # Multi-year forecasts: columns like "2025-盈利预测-收益"
                year_cols = []
                for col in frame.columns:
                    if "盈利预测-收益" in str(col):
                        try:
                            year = int(str(col).split("-")[0])
                            year_cols.append(year)
                        except ValueError:
                            continue

                for year in sorted(year_cols):
                    eps_col = f"{year}-盈利预测-收益"
                    pe_col = f"{year}-盈利预测-市盈率"
                    eps_raw = value_from(item, eps_col)
                    pe_raw = value_from(item, pe_col)
                    forecast_eps = safe_float(eps_raw)
                    forecast_pe = safe_float(pe_raw)
                    if forecast_eps is None and forecast_pe is None:
                        continue

                    forecast_period = f"{year}-12-31"
                    rows.append(
                        AnalystExpectationItem(
                            source=self.source,
                            stock_code=stock_code,
                            report_date=report_date,
                            forecast_period=forecast_period,
                            org_name=org_name,
                            report_title=title or None,
                            forecast_eps=forecast_eps,
                            forecast_pe=forecast_pe,
                            rating=rating,
                            source_url=pdf_link or None,
                            source_fetched_at=datetime.now().isoformat(),
                            confidence=0.85,
                            raw_json={
                                "source_api": "stock_research_report_em",
                                "industry": str(value_from(item, "行业", "industry") or ""),
                            },
                        )
                    )
        return rows

    def fetch_order_contract_events(self, start: str, end: str, stock_codes: list[str]) -> list[OrderContractEventItem]:
        notices = self._fetch_notice_rows(start, end, stock_codes)
        rows: list[OrderContractEventItem] = []
        for notice in notices:
            title = notice["title"]
            event_type, impact, _ = classify_event_title(title)
            if event_type != "major_contract":
                continue
            rows.append(
                OrderContractEventItem(
                    source=self.source,
                    stock_code=notice["stock_code"],
                    publish_date=notice["published_at"],
                    as_of_date=notice["published_at"],
                    event_type=event_type,
                    title=title,
                    summary=title,
                    impact_score=impact,
                    source_url=notice.get("source_url"),
                    confidence=0.7,
                    raw_json=notice,
                )
            )
        return rows

    def fetch_business_kpis(self, trading_date: str, stock_codes: list[str]) -> list[BusinessKpiItem]:
        raise UnsupportedDatasetError("akshare business_kpis are not configured")

    def fetch_risk_events(self, start: str, end: str, stock_codes: list[str]) -> list[RiskEventItem]:
        notices = self._fetch_notice_rows(start, end, stock_codes)
        rows: list[RiskEventItem] = []
        for notice in notices:
            title = notice["title"]
            event_type, impact, _ = classify_event_title(title)
            risk_type = risk_type_from_event_type(event_type)
            if risk_type is None:
                continue
            severity = "high" if impact <= -0.5 else "medium"
            rows.append(
                RiskEventItem(
                    source=self.source,
                    stock_code=notice["stock_code"],
                    event_date=notice["published_at"],
                    publish_date=notice["published_at"],
                    as_of_date=notice["published_at"],
                    risk_type=risk_type,
                    title=title,
                    severity=severity,
                    summary=title,
                    impact_score=impact,
                    source_url=notice.get("source_url"),
                    confidence=0.7,
                    raw_json=notice,
                )
            )
        return rows

    def _fetch_notice_rows(self, start: str, end: str, stock_codes: list[str]) -> list[dict[str, Any]]:
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare is not installed") from exc

        wanted = set(stock_codes)
        rows: list[dict[str, Any]] = []
        current = parse_date(start)
        end_date = parse_date(end)
        while current <= end_date:
            date_token = current.strftime("%Y%m%d")
            frame = ak.stock_notice_report(symbol="全部", date=date_token)
            for _, item in frame.iterrows():
                stock_code = normalize_stock_code(str(value_from(item, "代码", "code", "证券代码") or ""))
                if not stock_code or stock_code not in wanted:
                    continue
                title = str(value_from(item, "公告标题", "title") or "")
                published_at = normalize_date(value_from(item, "公告日期", "date") or current.isoformat())
                rows.append(
                    {
                        "stock_code": stock_code,
                        "published_at": published_at,
                        "title": title,
                        "source_url": value_from(item, "公告链接", "url", "链接"),
                    }
                )
            current += timedelta(days=1)
        return rows


class BaoStockProvider:
    source = "baostock"

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_stock_universe(self) -> list[StockUniverseItem]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc
        rows: list[StockUniverseItem] = []
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover
                raise RuntimeError(login.error_msg)
            try:
                query = bs.query_all_stock(day=date.today().isoformat())
                while query.next():
                    item = query.get_row_data()
                    stock_code = from_baostock_code(item[0])
                    rows.append(
                        StockUniverseItem(
                            stock_code=stock_code,
                            name=stock_code,
                            exchange=exchange_for_code(stock_code),
                            is_active=True,
                        )
                    )
            finally:  # pragma: no cover
                bs.logout()
        return rows

    def fetch_stock_codes_for_date(self, trading_date: str) -> list[str]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc
        codes: list[str] = []
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover
                raise RuntimeError(login.error_msg)
            try:
                query = bs.query_all_stock(day=trading_date)
                while query.next():
                    item = query.get_row_data()
                    stock_code = from_baostock_code(item[0])
                    if is_a_share_stock_code(stock_code):
                        codes.append(stock_code)
            finally:  # pragma: no cover
                bs.logout()
        return sorted(set(codes))

    def fetch_trading_calendar(self, start: str, end: str) -> list[TradingCalendarItem]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc
        rows: list[TradingCalendarItem] = []
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover
                raise RuntimeError(login.error_msg)
            try:
                query = bs.query_trade_dates(start_date=start, end_date=end)
                while query.next():
                    item = query.get_row_data()
                    rows.append(TradingCalendarItem(item[0], item[1] == "1", self.source))
            finally:  # pragma: no cover
                bs.logout()
        return rows

    def fetch_daily_prices(self, trading_date: str, stock_codes: list[str]) -> list[SourcePrice]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc

        rows: list[SourcePrice] = []
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover - depends on network
                raise RuntimeError(login.error_msg)
            try:
                for stock_code in stock_codes:
                    query = bs.query_history_k_data_plus(
                        to_baostock_code(stock_code),
                        "date,code,open,high,low,close,volume,amount",
                        start_date=trading_date,
                        end_date=trading_date,
                        frequency="d",
                        adjustflag="2",
                    )
                    while query.next():
                        item = query.get_row_data()
                        if not item[2]:
                            continue
                        rows.append(
                            SourcePrice(
                                source=self.source,
                                stock_code=stock_code,
                                trading_date=item[0],
                                open=float(item[2]),
                                high=float(item[3]),
                                low=float(item[4]),
                                close=float(item[5]),
                                volume=float(item[6] or 0),
                                amount=float(item[7] or 0),
                            )
                        )
            finally:  # pragma: no cover - depends on optional package
                bs.logout()
        return rows

    def fetch_daily_prices_range(self, start: str, end: str, stock_codes: list[str]) -> list[SourcePrice]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc

        rows: list[SourcePrice] = []
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover - depends on network
                raise RuntimeError(login.error_msg)
            try:
                for stock_code in stock_codes:
                    query = bs.query_history_k_data_plus(
                        to_baostock_code(stock_code),
                        "date,code,open,high,low,close,volume,amount",
                        start_date=start,
                        end_date=end,
                        frequency="d",
                        adjustflag="2",
                    )
                    while query.next():
                        item = query.get_row_data()
                        if not item[2]:
                            continue
                        rows.append(
                            SourcePrice(
                                source=self.source,
                                stock_code=stock_code,
                                trading_date=item[0],
                                open=float(item[2]),
                                high=float(item[3]),
                                low=float(item[4]),
                                close=float(item[5]),
                                volume=float(item[6] or 0),
                                amount=float(item[7] or 0),
                            )
                        )
            finally:  # pragma: no cover - depends on optional package
                bs.logout()
        return rows

    def fetch_index_prices(self, trading_date: str, index_codes: list[str]) -> list[SourceIndexPrice]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc
        rows: list[SourceIndexPrice] = []
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover
                raise RuntimeError(login.error_msg)
            try:
                for index_code in index_codes:
                    query = bs.query_history_k_data_plus(
                        to_baostock_code(index_code),
                        "date,code,open,high,low,close,volume,amount",
                        start_date=trading_date,
                        end_date=trading_date,
                        frequency="d",
                        adjustflag="2",
                    )
                    while query.next():
                        item = query.get_row_data()
                        if not item[2]:
                            continue
                        rows.append(
                            SourceIndexPrice(
                                source=self.source,
                                index_code=index_code,
                                trading_date=item[0],
                                open=float(item[2]),
                                high=float(item[3]),
                                low=float(item[4]),
                                close=float(item[5]),
                                volume=float(item[6] or 0),
                                amount=float(item[7] or 0),
                            )
                        )
            finally:  # pragma: no cover
                bs.logout()
        return rows

    def fetch_industries(self, trading_date: str, stock_codes: list[str]) -> list[IndustryItem]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc
        wanted = set(stock_codes)
        rows: list[IndustryItem] = []
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover
                raise RuntimeError(login.error_msg)
            try:
                query = bs.query_stock_industry(date=trading_date)
                while query.next():
                    item = dict(zip(query.fields, query.get_row_data()))
                    stock_code = from_baostock_code(item["code"])
                    if stock_code in wanted and item.get("industry"):
                        rows.append(IndustryItem(self.source, stock_code, item["industry"], item.get("updateDate") or trading_date))
            finally:  # pragma: no cover
                bs.logout()
        return rows

    def fetch_fundamentals(self, trading_date: str, stock_codes: list[str]) -> list[FundamentalMetricItem]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc
        rows: list[FundamentalMetricItem] = []
        candidates = report_period_candidates(trading_date)
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover
                raise RuntimeError(login.error_msg)
            try:
                for stock_code in stock_codes:
                    try:
                        bs_code = to_baostock_code(stock_code)
                    except ValueError:
                        continue
                    for year, quarter in candidates:
                        profit = baostock_query_first(bs.query_profit_data(bs_code, year=year, quarter=quarter))
                        if not profit:
                            continue
                        report_period = normalize_report_period(profit.get("statDate") or report_period_from_year_quarter(year, quarter))
                        as_of_date = conservative_visible_date(report_period, profit.get("pubDate"))
                        if as_of_date >= trading_date:
                            continue
                        prev_profit = baostock_query_first(bs.query_profit_data(bs_code, year=year - 1, quarter=quarter))
                        growth = baostock_query_first(bs.query_growth_data(bs_code, year=year, quarter=quarter))
                        balance = baostock_query_first(bs.query_balance_data(bs_code, year=year, quarter=quarter))
                        cash = baostock_query_first(bs.query_cash_flow_data(bs_code, year=year, quarter=quarter))
                        rows.append(
                            FundamentalMetricItem(
                                source=self.source,
                                stock_code=stock_code,
                                as_of_date=as_of_date,
                                report_period=report_period,
                                roe=safe_float(profit.get("roeAvg")),
                                revenue_growth=growth_from_values(
                                    safe_float(profit.get("MBRevenue")),
                                    safe_float(prev_profit.get("MBRevenue") if prev_profit else None),
                                ),
                                net_profit_growth=safe_float(growth.get("YOYNI") if growth else None),
                                gross_margin=safe_float(profit.get("gpMargin")),
                                debt_to_assets=safe_float(balance.get("liabilityToAsset") if balance else None),
                                operating_cashflow_to_profit=safe_float(cash.get("CFOToNP") if cash else None),
                                pe_percentile=None,
                                pb_percentile=None,
                                quality_note="baostock profit/growth/balance/cash",
                            )
                        )
                        break
            finally:  # pragma: no cover
                bs.logout()
        return rows

    def fetch_event_signals(self, start: str, end: str, stock_codes: list[str]) -> list[EventSignalItem]:
        """Fetch event signals from CNINFO (巨潮资讯网), independent of East Money."""
        try:
            import akshare as ak  # type: ignore[import-not-found]
        except Exception as e:
            logger.warning("BaoStock event fallback skipped: akshare not available (%s)", e)
            return []

        import pandas as pd  # type: ignore[import-not-found]

        rows: list[EventSignalItem] = []
        cninfo_start = start.replace("-", "")
        cninfo_end = end.replace("-", "")
        for stock_code in stock_codes:
            try:
                frame = ak.stock_zh_a_disclosure_report_cninfo(
                    symbol=stock_code.split(".")[0],
                    start_date=cninfo_start,
                    end_date=cninfo_end,
                )
            except Exception:
                continue
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            for _, item in frame.iterrows():
                title = str(item.get("公告标题") or "")
                if not title:
                    continue
                published_at = normalize_date(str(item.get("公告时间") or ""))
                if not published_at:
                    continue
                event_type, impact, sentiment = classify_event_title(title)
                rows.append(EventSignalItem(
                    source=self.source,
                    event_id=event_signal_id(self.source, published_at, stock_code, event_type, title),
                    trading_date=published_at,
                    published_at=published_at,
                    event_type=event_type,
                    title=title[:200],
                    summary=title[:500],
                    stock_code=stock_code,
                    impact_score=impact,
                    sentiment=sentiment,
                ))
        return rows

    def fetch_financial_actuals(self, trading_date: str, stock_codes: list[str]) -> list[FinancialActualItem]:
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("baostock is not installed") from exc
        rows: list[FinancialActualItem] = []
        candidates = report_period_candidates(trading_date)
        with default_socket_timeout(self.timeout_seconds):
            login = bs.login()
            if login.error_code != "0":  # pragma: no cover
                raise RuntimeError(login.error_msg)
            try:
                for stock_code in stock_codes:
                    try:
                        bs_code = to_baostock_code(stock_code)
                    except ValueError:
                        continue
                    for year, quarter in candidates:
                        profit = baostock_query_first(bs.query_profit_data(bs_code, year=year, quarter=quarter))
                        if not profit:
                            continue
                        report_period = normalize_report_period(profit.get("statDate") or report_period_from_year_quarter(year, quarter))
                        publish_date = normalize_date(profit.get("pubDate") or conservative_visible_date(report_period, None))
                        as_of_date = conservative_visible_date(report_period, profit.get("pubDate"))
                        if as_of_date >= trading_date:
                            continue
                        balance = baostock_query_first(bs.query_balance_data(bs_code, year=year, quarter=quarter))
                        cash = baostock_query_first(bs.query_cash_flow_data(bs_code, year=year, quarter=quarter))
                        rows.append(
                            FinancialActualItem(
                                source=self.source,
                                stock_code=stock_code,
                                report_period=report_period,
                                publish_date=publish_date,
                                as_of_date=as_of_date,
                                revenue=safe_float(profit.get("MBRevenue")),
                                net_profit=safe_float(profit.get("netProfit")),
                                deducted_net_profit=safe_float(profit.get("npParentCompanyOwners")),
                                eps=safe_float(profit.get("epsTTM")),
                                roe=safe_float(profit.get("roeAvg")),
                                gross_margin=safe_float(profit.get("gpMargin")),
                                operating_cashflow=safe_float(cash.get("CAToAsset") if cash else None),
                                debt_to_assets=safe_float(balance.get("liabilityToAsset") if balance else None),
                                raw_json={"profit": profit, "balance": balance, "cash": cash},
                            )
                        )
                        break
            finally:  # pragma: no cover
                bs.logout()
        return rows

    def fetch_analyst_expectations(self, trading_date: str, stock_codes: list[str]) -> list[AnalystExpectationItem]:
        raise UnsupportedDatasetError("baostock analyst_expectations are not configured")

    def fetch_order_contract_events(self, start: str, end: str, stock_codes: list[str]) -> list[OrderContractEventItem]:
        raise UnsupportedDatasetError("baostock order_contract_events are not configured")

    def fetch_business_kpis(self, trading_date: str, stock_codes: list[str]) -> list[BusinessKpiItem]:
        raise UnsupportedDatasetError("baostock business_kpis are not configured")

    def fetch_risk_events(self, start: str, end: str, stock_codes: list[str]) -> list[RiskEventItem]:
        raise UnsupportedDatasetError("baostock risk_events are not configured")


def sync_market_breadth(conn: sqlite3.Connection, trading_date: str) -> dict:
    """Sync full-market breadth data (advance/decline counts, limits, indices)."""
    from .market_breadth import ensure_market_breadth

    return ensure_market_breadth(conn, trading_date)


def sync_all_data(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
) -> dict[str, Any]:
    start = (parse_date(trading_date) - timedelta(days=45)).isoformat()
    return {
        "stock_universe": sync_stock_universe(conn, providers=providers),
        "trading_calendar": sync_trading_calendar(conn, start, trading_date, providers=providers),
        "daily_prices": sync_daily_prices(conn, trading_date, providers=providers),
        "index_prices": sync_index_prices(conn, trading_date, providers=providers),
        "market_breadth": sync_market_breadth(conn, trading_date),
        "canonical_prices": publish_canonical_prices(conn, trading_date),
        "market_environment": classify_market_environment(conn, trading_date),
    }


def sync_factors(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    stock_limit: int | None = DEFAULT_FACTOR_STOCK_LIMIT,
) -> dict[str, Any]:
    providers = providers or [BaoStockProvider(), AkShareProvider()]
    factor_start = (parse_date(trading_date) - timedelta(days=90)).isoformat()
    sector_start = (parse_date(trading_date) - timedelta(days=45)).isoformat()
    return {
        "industries": sync_industries(conn, trading_date, providers=providers),
        "sector_signals": sync_sector_signals_range(conn, sector_start, trading_date),
        "fundamentals": sync_fundamentals(conn, trading_date, providers=providers, limit=stock_limit),
        "event_signals": sync_event_signals(conn, factor_start, trading_date, providers=providers, limit=stock_limit),
    }


def backfill_factors_range(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    limit: int | None = DEFAULT_FACTOR_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    if start > end:
        raise ValueError("start must be <= end")
    days = open_trading_dates(conn, start, end)
    providers = providers or [BaoStockProvider(), AkShareProvider()]
    results = []
    for trading_date in days:
        result = {
            "trading_date": trading_date,
            "industries": sync_industries(conn, trading_date, providers=providers),
            "sector_signals": sync_sector_signals(conn, trading_date),
            "fundamentals": sync_fundamentals(
                conn,
                trading_date,
                providers=providers,
                limit=limit,
                offset=offset,
                batch_size=batch_size,
                resume=resume,
                throttle_seconds=throttle_seconds,
            ),
            "event_signals": sync_event_signals(
                conn,
                trading_date,
                trading_date,
                providers=providers,
                limit=limit,
                offset=offset,
                batch_size=batch_size,
                resume=resume,
                throttle_seconds=throttle_seconds,
            ),
        }
        results.append(result)
    return {"start": start, "end": end, "trading_days": len(days), "days": days, "results": results}


def sync_industries(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
) -> dict[str, Any]:
    providers = providers or [BaoStockProvider(), AkShareProvider()]
    stock_codes = repository.active_stock_codes(conn)
    source_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    filled: set[str] = set()
    for provider in providers:
        try:
            fetch = getattr(provider, "fetch_industries", None)
            if fetch is None:
                continue
            remaining = [code for code in stock_codes if code not in filled]
            rows = fetch(trading_date, remaining)
            for row in rows:
                if row.stock_code not in remaining or not row.industry:
                    continue
                conn.execute("UPDATE stocks SET industry = ? WHERE stock_code = ?", (row.industry, row.stock_code))
                filled.add(row.stock_code)
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="industries",
                trading_date=trading_date,
                status="ok",
                rows_loaded=len(rows),
                source_reliability=reliability_for_source(provider.source),
            )
            source_counts[provider.source] = len(rows)
        except Exception as exc:
            errors[provider.source] = str(exc)
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="industries",
                trading_date=trading_date,
                status="error",
                error=str(exc),
                source_reliability=reliability_for_source(provider.source),
            )
    conn.commit()
    return {"trading_date": trading_date, "sources": source_counts, "errors": errors, "rows": sum(source_counts.values())}


def sync_sector_signals_range(conn: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    days = open_trading_dates(conn, start, end)
    results = [sync_sector_signals(conn, trading_date) for trading_date in days]
    return {"start": start, "end": end, "trading_days": len(days), "rows": sum(item["rows"] for item in results), "results": results}


def sync_sector_signals(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    previous = previous_price_date(conn, trading_date)
    if previous is None:
        repository.record_data_source_status(
            conn,
            source="system",
            dataset="sector_signals",
            trading_date=trading_date,
            status="warning",
            error="missing previous trading day price data",
            source_reliability="high",
        )
        conn.commit()
        return {"trading_date": trading_date, "rows": 0, "status": "warning"}
    rows = conn.execute(
        """
        SELECT s.industry,
               AVG(CASE WHEN p0.close > 0 THEN p1.close / p0.close - 1 ELSE NULL END) AS sector_return_pct,
               SUM(p1.amount) AS amount,
               SUM(p0.amount) AS previous_amount,
               COUNT(*) AS stock_count
        FROM daily_prices p1
        JOIN daily_prices p0 ON p0.stock_code = p1.stock_code AND p0.trading_date = ?
        JOIN stocks s ON s.stock_code = p1.stock_code
        WHERE p1.trading_date = ?
          AND s.industry IS NOT NULL
          AND s.industry != ''
        GROUP BY s.industry
        HAVING stock_count >= 1
        """,
        (previous, trading_date),
    ).fetchall()
    ordered = sorted(rows, key=lambda row: float(row["sector_return_pct"] or 0), reverse=True)
    total = len(ordered)
    for rank, row in enumerate(ordered, start=1):
        amount = float(row["amount"] or 0)
        previous_amount = float(row["previous_amount"] or 0)
        volume_surge = amount / previous_amount - 1 if previous_amount > 0 else 0
        theme_strength = clamp((total - rank + 1) / max(1, total) * 0.7 + normalize(volume_surge, -0.3, 1.0) * 0.3, 0, 1)
        repository.upsert_sector_theme_signal(
            conn,
            trading_date=trading_date,
            industry=row["industry"],
            sector_return_pct=float(row["sector_return_pct"] or 0),
            relative_strength_rank=rank,
            volume_surge=volume_surge,
            theme_strength=theme_strength,
            catalyst_count=0,
            summary=f"{row['industry']} rank {rank}/{total}, return {float(row['sector_return_pct'] or 0):.2%}",
            source="daily_prices",
        )
    repository.record_data_source_status(
        conn,
        source="system",
        dataset="sector_signals",
        trading_date=trading_date,
        status="ok",
        rows_loaded=len(ordered),
        source_reliability="high",
    )
    conn.commit()
    return {"trading_date": trading_date, "rows": len(ordered), "status": "ok"}


def sync_fundamentals(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    stock_codes: list[str] | None = None,
    limit: int | None = DEFAULT_FACTOR_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    providers = providers or [BaoStockProvider()]
    selected_codes = stock_codes or liquid_stock_codes_before(conn, trading_date, limit=limit, offset=offset)
    source_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for provider in providers:
        fetch = getattr(provider, "fetch_fundamentals", None)
        if fetch is None:
            continue
        rows_loaded = 0
        failed_chunks: list[dict[str, Any]] = []
        skipped_provider = False
        provider_codes = selected_codes
        if resume:
            existing = fundamental_stock_codes_before(conn, trading_date, selected_codes, provider.source)
            provider_codes = [code for code in selected_codes if code not in existing]
        for chunk_index, chunk in enumerate(chunked(provider_codes, batch_size), start=1):
            try:
                rows = fetch(trading_date, chunk)
                for row in rows:
                    repository.upsert_fundamental_metrics(conn, **row.__dict__)
                    rows_loaded += 1
                conn.commit()
            except UnsupportedDatasetError as exc:
                failed_chunks = []
                repository.record_data_source_status(
                    conn,
                    source=provider.source,
                    dataset="fundamentals",
                    trading_date=trading_date,
                    status="skipped",
                    rows_loaded=0,
                    error=str(exc),
                    source_reliability=reliability_for_source(provider.source),
                )
                source_counts[provider.source] = 0
                skipped_provider = True
                break
            except Exception as exc:
                failed_chunks.append({"chunk_index": chunk_index, "stock_count": len(chunk), "error": str(exc)})
            if throttle_seconds > 0:
                time.sleep(throttle_seconds)
        if skipped_provider:
            continue
        status = "warning" if failed_chunks else "ok"
        if failed_chunks and rows_loaded == 0:
            status = "error"
        repository.record_data_source_status(
            conn,
            source=provider.source,
            dataset="fundamentals",
            trading_date=trading_date,
            status=status,
            rows_loaded=rows_loaded,
            warning_count=len(failed_chunks),
            error=repository.dumps(failed_chunks) if failed_chunks else None,
            source_reliability=reliability_for_source(provider.source),
        )
        source_counts[provider.source] = rows_loaded
        if failed_chunks:
            errors[provider.source] = repository.dumps(failed_chunks)
    conn.commit()
    return {"trading_date": trading_date, "sources": source_counts, "errors": errors, "selected_stocks": len(selected_codes)}


def sync_event_signals(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    stock_codes: list[str] | None = None,
    limit: int | None = DEFAULT_FACTOR_STOCK_LIMIT,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    providers = providers or [AkShareProvider()]
    selected_codes = stock_codes or liquid_stock_codes_before(conn, end, limit=limit, offset=offset)
    source_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    dates = date_range(start, end)
    for provider in providers:
        fetch = getattr(provider, "fetch_event_signals", None)
        if fetch is None:
            continue
        rows_loaded = 0
        failed_chunks: list[dict[str, Any]] = []
        skipped_dates = 0
        for date_index, event_date in enumerate(dates, start=1):
            if resume and data_source_status_is_ok(conn, provider.source, "event_signals", event_date):
                skipped_dates += 1
                continue
            day_loaded = 0
            try:
                rows = fetch(event_date, event_date, selected_codes)
                for row in rows:
                    if resume and event_signal_exists(conn, row.event_id):
                        continue
                    repository.upsert_event_signal(conn, **row.__dict__)
                    rows_loaded += 1
                    day_loaded += 1
                repository.record_data_source_status(
                    conn,
                    source=provider.source,
                    dataset="event_signals",
                    trading_date=event_date,
                    status="ok",
                    rows_loaded=day_loaded,
                    source_reliability=reliability_for_source(provider.source),
                )
                conn.commit()
            except Exception as exc:
                failed_chunks.append({"date_index": date_index, "trading_date": event_date, "stock_count": len(selected_codes), "error": str(exc)})
                repository.record_data_source_status(
                    conn,
                    source=provider.source,
                    dataset="event_signals",
                    trading_date=event_date,
                    status="error",
                    error=str(exc),
                    source_reliability=reliability_for_source(provider.source),
                )
                conn.commit()
            if throttle_seconds > 0:
                time.sleep(throttle_seconds)
        status = "warning" if failed_chunks else "ok"
        if failed_chunks and rows_loaded == 0:
            status = "error"
        repository.record_data_source_status(
            conn,
            source=provider.source,
            dataset="event_signals",
            trading_date=end,
            status=status,
            rows_loaded=rows_loaded,
            warning_count=len(failed_chunks),
            error=repository.dumps(failed_chunks) if failed_chunks else None,
            source_reliability=reliability_for_source(provider.source),
        )
        source_counts[provider.source] = rows_loaded
        if failed_chunks:
            errors[provider.source] = repository.dumps(failed_chunks)
    conn.commit()
    return {
        "start": start,
        "end": end,
        "dates": len(dates),
        "sources": source_counts,
        "errors": errors,
        "selected_stocks": len(selected_codes),
    }


def backfill_daily_prices_range(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    stock_codes: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    max_retries: int = 1,
    throttle_seconds: float = 0.0,
    publish_canonical: bool = True,
    sync_indexes: bool = False,
    classify_environment: bool = False,
    index_codes: list[str] | None = None,
    historical_universe_date: str | None = None,
) -> dict[str, Any]:
    if start > end:
        raise ValueError("start must be <= end")
    days = open_trading_dates(conn, start, end)
    selected_stock_codes = stock_codes or historical_stock_codes_for_date(
        providers or [AkShareProvider(), BaoStockProvider()],
        historical_universe_date,
    )
    if selected_stock_codes is not None:
        selected_stock_codes = filter_known_active_stock_codes(conn, selected_stock_codes)
    daily_range = sync_daily_prices_range(
        conn,
        start,
        end,
        days,
        providers=providers,
        stock_codes=selected_stock_codes,
        limit=limit,
        offset=offset,
        batch_size=batch_size,
        resume=resume,
        max_retries=max_retries,
        throttle_seconds=throttle_seconds,
    )
    results: list[dict[str, Any]] = []
    for trading_date in days:
        day_result: dict[str, Any] = {
            "trading_date": trading_date,
            "daily_prices": daily_range["days"].get(trading_date, {"sources": {}, "skipped_existing": {}}),
        }
        if sync_indexes:
            day_result["index_prices"] = sync_index_prices(
                conn,
                trading_date,
                providers=providers,
                index_codes=index_codes,
            )
        if publish_canonical:
            day_result["canonical_prices"] = publish_canonical_prices(conn, trading_date)
        if classify_environment:
            day_result["market_environment"] = classify_market_environment(conn, trading_date)
        results.append(day_result)
    return {
        "start": start,
        "end": end,
        "trading_days": len(days),
        "days": days,
        "source_rows_loaded": daily_range["sources"],
        "warning_days": daily_range["warning_days"],
        "failed_chunks": daily_range["failed_chunks"],
        "selected_stocks": daily_range["selected_stocks"],
        "results": results,
    }


def sync_daily_prices_range(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    trading_dates: list[str],
    providers: list[MarketDataProvider] | None = None,
    *,
    stock_codes: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = True,
    max_retries: int = 1,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    providers = providers or [AkShareProvider(), BaoStockProvider()]
    selected_codes = stock_codes or repository.active_stock_codes(conn)
    selected_codes = apply_stock_window(selected_codes, offset=offset, limit=limit)
    day_results: dict[str, dict[str, Any]] = {
        trading_date: {"sources": {}, "skipped_existing": {}, "failed_chunks": {}}
        for trading_date in trading_dates
    }
    source_totals: dict[str, int] = {}
    failed_chunks: dict[str, list[dict[str, Any]]] = {}
    trading_date_set = set(trading_dates)

    for provider in providers:
        source_totals.setdefault(provider.source, 0)
        provider_codes = selected_codes
        if resume:
            complete = repository.complete_source_daily_price_codes(
                conn,
                source=provider.source,
                trading_dates=trading_dates,
                stock_codes=selected_codes,
            )
            provider_codes = [code for code in selected_codes if code not in complete]
            for trading_date in trading_dates:
                day_results[trading_date]["skipped_existing"][provider.source] = len(complete)

        rows_by_date = {trading_date: 0 for trading_date in trading_dates}
        provider_failed_chunks: list[dict[str, Any]] = []
        for chunk_index, chunk in enumerate(chunked(provider_codes, batch_size), start=1):
            try:
                rows = fetch_daily_prices_range_with_retries(
                    provider,
                    start,
                    end,
                    chunk,
                    max_retries=max_retries,
                    throttle_seconds=throttle_seconds,
                )
                for row in rows:
                    if row.trading_date not in trading_date_set:
                        continue
                    repository.upsert_source_daily_price(conn, **row.__dict__)
                    rows_by_date[row.trading_date] += 1
                    source_totals[provider.source] = source_totals.get(provider.source, 0) + 1
                conn.commit()
            except Exception as exc:
                provider_failed_chunks.append(
                    {
                        "chunk_index": chunk_index,
                        "first_stock_code": chunk[0] if chunk else None,
                        "last_stock_code": chunk[-1] if chunk else None,
                        "stock_count": len(chunk),
                        "error": str(exc),
                    }
                )
            if throttle_seconds > 0:
                time.sleep(throttle_seconds)

        if provider_failed_chunks:
            failed_chunks[provider.source] = provider_failed_chunks
        for trading_date in trading_dates:
            rows_loaded = rows_by_date[trading_date]
            status = "warning" if provider_failed_chunks else "ok"
            if provider_failed_chunks and rows_loaded == 0:
                status = "error"
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="daily_prices",
                trading_date=trading_date,
                status=status,
                rows_loaded=rows_loaded,
                warning_count=len(provider_failed_chunks),
                error=repository.dumps(provider_failed_chunks) if provider_failed_chunks else None,
                source_reliability=reliability_for_source(provider.source),
            )
            day_results[trading_date]["sources"][provider.source] = rows_loaded
            if provider_failed_chunks:
                day_results[trading_date]["failed_chunks"][provider.source] = provider_failed_chunks
    conn.commit()
    warning_days = sum(1 for result in day_results.values() if result["failed_chunks"])
    return {
        "start": start,
        "end": end,
        "sources": source_totals,
        "failed_chunks": failed_chunks,
        "selected_stocks": len(selected_codes),
        "warning_days": warning_days,
        "days": day_results,
        "batch_size": batch_size,
        "offset": offset,
        "limit": limit,
        "resume": resume,
    }


def historical_stock_codes_for_date(
    providers: list[MarketDataProvider],
    trading_date: str | None,
) -> list[str] | None:
    if not trading_date:
        return None
    codes: set[str] = set()
    for provider in providers:
        fetch_codes = getattr(provider, "fetch_stock_codes_for_date", None)
        if fetch_codes is None:
            continue
        codes.update(fetch_codes(trading_date))
    return sorted(codes) if codes else None


def filter_known_active_stock_codes(conn: sqlite3.Connection, stock_codes: list[str]) -> list[str]:
    known = set(repository.active_stock_codes(conn))
    return [code for code in stock_codes if code in known and is_a_share_stock_code(code)]


def previous_price_date(conn: sqlite3.Connection, trading_date: str) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(trading_date) AS trading_date
        FROM daily_prices
        WHERE trading_date < ?
        """,
        (trading_date,),
    ).fetchone()
    return row["trading_date"] if row and row["trading_date"] else None


def liquid_stock_codes_before(
    conn: sqlite3.Connection,
    trading_date: str,
    *,
    limit: int | None,
    offset: int = 0,
) -> list[str]:
    price_date = previous_price_date(conn, trading_date)
    if price_date is None:
        codes = [c for c in (normalize_stock_code(c) for c in repository.active_stock_codes(conn)) if c is not None]
        return apply_stock_window(codes, offset=offset, limit=limit)
    query_limit = -1 if limit is None else limit
    rows = conn.execute(
        """
        SELECT s.stock_code
        FROM stocks s
        JOIN daily_prices p ON p.stock_code = s.stock_code
        WHERE p.trading_date = ?
          AND s.listing_status = 'active'
          AND COALESCE(s.is_st, 0) = 0
        ORDER BY p.amount DESC, s.stock_code
        LIMIT ? OFFSET ?
        """,
        (price_date, query_limit, offset),
    ).fetchall()
    codes: list[str] = []
    for row in rows:
        normalized = normalize_stock_code(row["stock_code"])
        if normalized:
            codes.append(normalized)
    return codes


def fundamental_stock_codes_before(
    conn: sqlite3.Connection,
    trading_date: str,
    stock_codes: list[str],
    source: str,
) -> set[str]:
    if not stock_codes:
        return set()
    placeholders = ",".join("?" for _ in stock_codes)
    rows = conn.execute(
        f"""
        SELECT DISTINCT stock_code FROM fundamental_metrics
        WHERE as_of_date < ?
          AND source = ?
          AND stock_code IN ({placeholders})
        """,
        (trading_date, source, *stock_codes),
    ).fetchall()
    return {row["stock_code"] for row in rows}


def event_signal_exists(conn: sqlite3.Connection, event_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM event_signals WHERE event_id = ?", (event_id,)).fetchone()
    return row is not None


def data_source_status_is_ok(conn: sqlite3.Connection, source: str, dataset: str, trading_date: str) -> bool:
    row = conn.execute(
        """
        SELECT status FROM data_sources
        WHERE source = ? AND dataset = ? AND trading_date = ?
        """,
        (source, dataset, trading_date),
    ).fetchone()
    return bool(row and row["status"] == "ok")


def date_range(start: str, end: str) -> list[str]:
    start_date = parse_date(start)
    end_date = parse_date(end)
    days: list[str] = []
    current = start_date
    while current <= end_date:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def open_trading_dates(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT trading_date FROM trading_days
        WHERE trading_date BETWEEN ? AND ?
          AND is_open = 1
        ORDER BY trading_date
        """,
        (start, end),
    ).fetchall()
    if rows:
        return [row["trading_date"] for row in rows]
    start_date = parse_date(start)
    end_date = parse_date(end)
    days: list[str] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def sync_stock_universe(
    conn: sqlite3.Connection,
    providers: list[MarketDataProvider] | None = None,
) -> dict[str, Any]:
    providers = providers or [AkShareProvider()]
    source_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for provider in providers:
        try:
            rows = provider.fetch_stock_universe()
            for row in rows:
                repository.upsert_stock(
                    conn,
                    row.stock_code,
                    row.name,
                    exchange=row.exchange,
                    industry=row.industry,
                    list_date=row.list_date,
                    is_st=row.is_st,
                    listing_status="active" if row.is_active else "inactive",
                )
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="stock_universe",
                status="ok",
                rows_loaded=len(rows),
                source_reliability=reliability_for_source(provider.source),
            )
            source_counts[provider.source] = len(rows)
        except Exception as exc:
            errors[provider.source] = str(exc)
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="stock_universe",
                status="error",
                error=str(exc),
                source_reliability=reliability_for_source(provider.source),
            )
    conn.commit()
    return {"sources": source_counts, "errors": errors, "rows": sum(source_counts.values())}


def sync_trading_calendar(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    providers: list[MarketDataProvider] | None = None,
) -> dict[str, Any]:
    providers = providers or [AkShareProvider()]
    source_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for provider in providers:
        try:
            rows = provider.fetch_trading_calendar(start, end)
            for row in rows:
                repository.upsert_trading_day(conn, row.trading_date, row.is_open)
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="trading_calendar",
                status="ok",
                rows_loaded=len(rows),
                trading_date=end,
                source_reliability=reliability_for_source(provider.source),
            )
            source_counts[provider.source] = len(rows)
        except Exception as exc:
            errors[provider.source] = str(exc)
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="trading_calendar",
                trading_date=end,
                status="error",
                error=str(exc),
                source_reliability=reliability_for_source(provider.source),
            )
    conn.commit()
    return {"start": start, "end": end, "sources": source_counts, "errors": errors}


def sync_daily_prices(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
    *,
    stock_codes: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
    batch_size: int = 100,
    resume: bool = False,
    max_retries: int = 1,
    throttle_seconds: float = 0.0,
) -> dict[str, Any]:
    providers = providers or [AkShareProvider(), BaoStockProvider()]
    selected_codes = stock_codes or repository.active_stock_codes(conn)
    selected_codes = apply_stock_window(selected_codes, offset=offset, limit=limit)
    source_counts: dict[str, int] = {}
    skipped_existing: dict[str, int] = {}
    errors: dict[str, str] = {}
    failed_chunks: dict[str, list[dict[str, Any]]] = {}
    for provider in providers:
        provider_codes = selected_codes
        if resume:
            existing = repository.existing_source_daily_price_codes(
                conn,
                source=provider.source,
                trading_date=trading_date,
                stock_codes=selected_codes,
            )
            provider_codes = [code for code in selected_codes if code not in existing]
            skipped_existing[provider.source] = len(existing)
        rows_loaded = 0
        provider_failed_chunks: list[dict[str, Any]] = []
        try:
            for chunk_index, chunk in enumerate(chunked(provider_codes, batch_size), start=1):
                try:
                    rows = fetch_daily_prices_with_retries(
                        provider,
                        trading_date,
                        chunk,
                        max_retries=max_retries,
                        throttle_seconds=throttle_seconds,
                    )
                    for row in rows:
                        repository.upsert_source_daily_price(conn, **row.__dict__)
                    rows_loaded += len(rows)
                    conn.commit()
                except Exception as exc:
                    provider_failed_chunks.append(
                        {
                            "chunk_index": chunk_index,
                            "first_stock_code": chunk[0] if chunk else None,
                            "last_stock_code": chunk[-1] if chunk else None,
                            "stock_count": len(chunk),
                            "error": str(exc),
                        }
                    )
                if throttle_seconds > 0:
                    time.sleep(throttle_seconds)
            status = "warning" if provider_failed_chunks else "ok"
            if provider_failed_chunks and rows_loaded == 0:
                status = "error"
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="daily_prices",
                trading_date=trading_date,
                status=status,
                rows_loaded=rows_loaded,
                warning_count=len(provider_failed_chunks),
                error=repository.dumps(provider_failed_chunks) if provider_failed_chunks else None,
                source_reliability=reliability_for_source(provider.source),
            )
            source_counts[provider.source] = rows_loaded
            if provider_failed_chunks:
                failed_chunks[provider.source] = provider_failed_chunks
        except Exception as exc:
            errors[provider.source] = str(exc)
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="daily_prices",
                trading_date=trading_date,
                status="error",
                error=str(exc),
                source_reliability=reliability_for_source(provider.source),
            )
    conn.commit()
    return {
        "trading_date": trading_date,
        "sources": source_counts,
        "errors": errors,
        "failed_chunks": failed_chunks,
        "selected_stocks": len(selected_codes),
        "skipped_existing": skipped_existing,
        "batch_size": batch_size,
        "offset": offset,
        "limit": limit,
        "resume": resume,
    }


def sync_index_prices(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
    index_codes: list[str] | None = None,
) -> dict[str, Any]:
    providers = providers or [AkShareProvider(), BaoStockProvider()]
    index_codes = index_codes or DEFAULT_INDEX_CODES
    source_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for provider in providers:
        try:
            rows = provider.fetch_index_prices(trading_date, index_codes)
            for row in rows:
                repository.upsert_source_index_price(conn, **row.__dict__)
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="index_prices",
                trading_date=trading_date,
                status="ok",
                rows_loaded=len(rows),
                source_reliability=reliability_for_source(provider.source),
            )
            source_counts[provider.source] = len(rows)
        except Exception as exc:
            errors[provider.source] = str(exc)
            repository.record_data_source_status(
                conn,
                source=provider.source,
                dataset="index_prices",
                trading_date=trading_date,
                status="error",
                error=str(exc),
                source_reliability=reliability_for_source(provider.source),
            )
    published = publish_index_prices(conn, trading_date, index_codes)
    conn.commit()
    return {"trading_date": trading_date, "sources": source_counts, "published": published, "errors": errors}


def publish_canonical_prices(conn: sqlite3.Connection, trading_date: str) -> dict[str, Any]:
    checks = compare_and_publish_prices(conn, trading_date)
    warning_count = sum(1 for check in checks if check.status != "ok")
    repository.record_data_source_status(
        conn,
        source="system",
        dataset="canonical_prices",
        trading_date=trading_date,
        status="warning" if warning_count else "ok",
        rows_loaded=len(checks) - sum(1 for check in checks if check.status == "missing_all"),
        warning_count=warning_count,
        source_reliability="high",
    )
    conn.commit()
    return {"checks": len(checks), "warnings": warning_count}


def publish_index_prices(conn: sqlite3.Connection, trading_date: str, index_codes: list[str]) -> int:
    published = 0
    for index_code in index_codes:
        row = conn.execute(
            """
            SELECT * FROM source_index_prices
            WHERE index_code = ? AND trading_date = ?
            ORDER BY CASE source WHEN 'akshare' THEN 0 WHEN 'baostock' THEN 1 ELSE 2 END
            LIMIT 1
            """,
            (index_code, trading_date),
        ).fetchone()
        if row is None:
            continue
        repository.upsert_index_price(
            conn,
            index_code=index_code,
            trading_date=trading_date,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            amount=float(row["amount"]),
            source=row["source"],
        )
        published += 1
    return published


def classify_market_environment(
    conn: sqlite3.Connection,
    trading_date: str,
    index_code: str = "000300.SH",
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT * FROM index_prices
        WHERE index_code = ? AND trading_date < ?
        ORDER BY trading_date DESC
        LIMIT 20
        """,
        (index_code, trading_date),
    ).fetchall()
    if len(rows) < 20:
        repository.upsert_trading_day(
            conn,
            trading_date,
            True,
            market_trend="unknown",
            trend_type="unknown",
            volatility_level="unknown",
            volume_level="unknown",
            turnover_level="unknown",
            market_environment="unknown",
        )
        conn.commit()

        # Write unknown to market_environment_logs too
        import hashlib as _hash
        log_id = "mel_" + _hash.sha1(f"market_env_{trading_date}".encode()).hexdigest()[:12]
        try:
            conn.execute(
                "INSERT INTO market_environment_logs(log_id, trading_date, market_environment, trend_type, volatility_level, breadth_up_count, breadth_down_count, limit_up_count, limit_down_count) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0)",
                (log_id, trading_date, "unknown", "unknown", "unknown"),
            )
            conn.commit()
        except Exception:
            pass

        return {"market_environment": "unknown", "reason": "insufficient index history", "history_days": len(rows)}
    ordered = list(rows)[::-1]
    closes = [float(row["close"]) for row in ordered]
    amounts = [float(row["amount"] or 0) for row in ordered]
    returns = daily_returns(closes)
    period_return = closes[-1] / closes[0] - 1 if closes[0] else 0.0
    volatility = stdev(returns)
    avg_amount = mean(amounts)
    turnover_ratio = amounts[-1] / avg_amount if avg_amount else 1.0
    trend_type = "uptrend" if period_return > 0.03 else "downtrend" if period_return < -0.03 else "range"
    volatility_level = "high" if volatility > 0.02 else "low" if volatility < 0.008 else "medium"
    turnover_level = "expanding" if turnover_ratio > 1.2 else "contracting" if turnover_ratio < 0.8 else "normal"
    environment = f"{trend_type}_{volatility_level}_{turnover_level}"
    repository.upsert_trading_day(
        conn,
        trading_date,
        True,
        market_trend=trend_type,
        trend_type=trend_type,
        volatility_level=volatility_level,
        volume_level=turnover_level,
        turnover_level=turnover_level,
        market_environment=environment,
        index_return_pct=period_return,
    )
    conn.commit()

    # Write to market_environment_logs for environment-layered tracking
    breadth = conn.execute(
        "SELECT advance_count, decline_count, limit_up_count, limit_down_count FROM market_overview_daily WHERE trading_date = ?",
        (trading_date,),
    ).fetchone()
    breadth_up = breadth["advance_count"] if breadth else 0
    breadth_down = breadth["decline_count"] if breadth else 0
    limit_up = breadth["limit_up_count"] if breadth else 0
    limit_down = breadth["limit_down_count"] if breadth else 0

    import hashlib as _hash
    log_id = "mel_" + _hash.sha1(f"market_env_{trading_date}".encode()).hexdigest()[:12]
    conn.execute(
        """
        INSERT INTO market_environment_logs(
          log_id, trading_date, market_environment, trend_type, volatility_level,
          breadth_up_count, breadth_down_count, limit_up_count, limit_down_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trading_date) DO UPDATE SET
          market_environment = excluded.market_environment,
          trend_type = excluded.trend_type,
          volatility_level = excluded.volatility_level,
          breadth_up_count = excluded.breadth_up_count,
          breadth_down_count = excluded.breadth_down_count,
          limit_up_count = excluded.limit_up_count,
          limit_down_count = excluded.limit_down_count
        """,
        (log_id, trading_date, environment, trend_type, volatility_level,
         breadth_up, breadth_down, limit_up, limit_down),
    )
    conn.commit()

    return {
        "market_environment": environment,
        "trend_type": trend_type,
        "volatility_level": volatility_level,
        "turnover_level": turnover_level,
        "index_return_pct": period_return,
    }


def sync_daily_sources(
    conn: sqlite3.Connection,
    trading_date: str,
    providers: list[MarketDataProvider] | None = None,
) -> dict[str, object]:
    providers = providers or [AkShareProvider(), BaoStockProvider()]
    daily = sync_daily_prices(conn, trading_date, providers)
    canonical = publish_canonical_prices(conn, trading_date)
    warnings = len(daily.get("errors", {})) + int(canonical["warnings"])
    return {
        "trading_date": trading_date,
        "sources": daily["sources"],
        "checks": canonical["checks"],
        "warnings": warnings,
    }


def apply_stock_window(stock_codes: list[str], *, offset: int = 0, limit: int | None = None) -> list[str]:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    end = None if limit is None else offset + limit
    return stock_codes[offset:end]


def chunked(values: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        raise ValueError("batch_size must be positive")
    return [values[index : index + size] for index in range(0, len(values), size)]


def fetch_daily_prices_with_retries(
    provider: MarketDataProvider,
    trading_date: str,
    stock_codes: list[str],
    *,
    max_retries: int,
    throttle_seconds: float,
) -> list[SourcePrice]:
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    attempts = max_retries + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return provider.fetch_daily_prices(trading_date, stock_codes)
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1 and throttle_seconds > 0:
                time.sleep(throttle_seconds)
    assert last_error is not None
    raise last_error


def fetch_daily_prices_range_with_retries(
    provider: MarketDataProvider,
    start: str,
    end: str,
    stock_codes: list[str],
    *,
    max_retries: int,
    throttle_seconds: float,
) -> list[SourcePrice]:
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    attempts = max_retries + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            fetch_range = getattr(provider, "fetch_daily_prices_range", None)
            if fetch_range is not None:
                return fetch_range(start, end, stock_codes)
            rows: list[SourcePrice] = []
            current = parse_date(start)
            end_date = parse_date(end)
            while current <= end_date:
                if current.weekday() < 5:
                    rows.extend(provider.fetch_daily_prices(current.isoformat(), stock_codes))
                current += timedelta(days=1)
            return rows
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1 and throttle_seconds > 0:
                time.sleep(throttle_seconds)
    assert last_error is not None
    raise last_error


_socket_timeout_lock = threading.Lock()


@contextmanager
def default_socket_timeout(seconds: float):
    previous = socket.getdefaulttimeout()
    with _socket_timeout_lock:
        socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        with _socket_timeout_lock:
            socket.setdefaulttimeout(previous)


def normalize_stock_code(raw_code: str) -> str | None:
    code = raw_code.strip().lower().replace("sh.", "").replace("sz.", "").replace("bj.", "")
    code = code.replace("sh", "").replace("sz", "").replace("bj", "") if len(code) > 6 else code
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) != 6:
        return None
    if digits.startswith(("6", "9")):
        exchange = "SH"
    elif digits.startswith(("0", "2", "3")):
        exchange = "SZ"
    elif digits.startswith(("4", "8")):
        exchange = "BJ"
    else:
        exchange = "SZ"
    return f"{digits}.{exchange}"


def exchange_for_code(stock_code: str) -> str:
    suffix = stock_code.split(".")[-1]
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix, suffix)


def to_baostock_code(stock_code: str) -> str:
    if "." not in stock_code:
        raise ValueError(f"Invalid stock_code format: {stock_code!r}, expected format 'CODE.EXCHANGE'")
    code, exchange = stock_code.split(".")
    return f"{exchange.lower()}.{code}"


def from_baostock_code(code: str) -> str:
    if "." not in code:
        raise ValueError(f"Invalid baostock code format: {code!r}, expected format 'exchange.digits'")
    exchange, digits = code.split(".")
    return f"{digits}.{exchange.upper()}"


def is_a_share_stock_code(stock_code: str) -> bool:
    if "." not in stock_code:
        return False
    code, exchange = stock_code.split(".")
    if exchange == "SH":
        return code.startswith(("6", "9"))
    if exchange == "SZ":
        if code.startswith("399"):
            return False
        return code.startswith(("0", "2", "3"))
    if exchange == "BJ":
        return code.startswith(("4", "8"))
    return False


def to_akshare_index_code(index_code: str) -> str:
    code, exchange = index_code.split(".")
    prefix = "sh" if exchange == "SH" else "sz"
    return f"{prefix}{code}"


def baostock_query_first(query: Any) -> dict[str, str] | None:
    while query.next():
        return dict(zip(query.fields, query.get_row_data()))
    return None


def report_period_candidates(trading_date: str) -> list[tuple[int, int]]:
    target = parse_date(trading_date)
    candidates: list[tuple[int, int]] = []
    for year in range(target.year, target.year - 3, -1):
        for quarter in (4, 3, 2, 1):
            period = report_period_from_year_quarter(year, quarter)
            if conservative_visible_date(period, None) < trading_date:
                candidates.append((year, quarter))
    return candidates


def report_period_from_year_quarter(year: int, quarter: int) -> str:
    month_day = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[quarter]
    return f"{year}-{month_day}"


def normalize_report_period(value: str) -> str:
    return normalize_date(value)


def conservative_visible_date(report_period: str, published_at: str | None) -> str:
    if published_at:
        return normalize_date(published_at)
    period = parse_date(normalize_report_period(report_period))
    if period.month == 3:
        return f"{period.year}-06-01"
    if period.month == 6:
        return f"{period.year}-09-01"
    if period.month == 9:
        return f"{period.year}-11-15"
    return f"{period.year + 1}-05-01"


def safe_float(value: Any) -> float | None:
    import math
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        v = float(text)
        return None if math.isnan(v) else v
    except ValueError:
        return None


def growth_from_values(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return current / previous - 1


def classify_event_title(title: str) -> tuple[str, float, float]:
    text = title.lower()
    positive = {
        "major_contract": ("合同", "中标", "订单", "项目", "签署"),
        "buyback": ("回购",),
        "earnings_positive": ("预增", "扭亏", "增长", "业绩快报"),
    }
    negative = {
        "shareholder_reduction": ("减持",),
        "litigation": ("诉讼", "仲裁"),
        "penalty": ("处罚", "问询函", "监管函", "立案"),
        "delisting_risk": ("退市", "风险警示", "st", "*st"),
    }
    for event_type, keywords in negative.items():
        if any(keyword in text for keyword in keywords):
            return event_type, -0.55, -0.6
    for event_type, keywords in positive.items():
        if any(keyword in text for keyword in keywords):
            return event_type, 0.45, 0.45
    return "announcement", 0.0, 0.0


def risk_type_from_event_type(event_type: str) -> str | None:
    mapping = {
        "shareholder_reduction": "shareholder_reduction",
        "litigation": "litigation",
        "penalty": "regulatory_penalty",
        "delisting_risk": "delisting_risk",
    }
    return mapping.get(event_type)


def event_signal_id(source: str, published_at: str, stock_code: str | None, event_type: str, title: str) -> str:
    raw = f"{source}:{published_at}:{stock_code or ''}:{event_type}:{title}"
    return "evt_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def is_st_name(name: str) -> bool:
    normalized = name.upper()
    return "ST" in normalized or "退" in name


def value_from(row: Any, *keys: str) -> Any:
    for key in keys:
        try:
            value = row[key]
        except Exception:
            continue
        if value is not None:
            return value
    return None


def normalize_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)[:10]
    if "/" in text:
        return datetime.strptime(text, "%Y/%m/%d").date().isoformat()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def reliability_for_source(source: str) -> str:
    return {"akshare": "medium", "baostock": "medium", "system": "high", "demo": "low"}.get(source, "medium")


def daily_returns(closes: list[float]) -> list[float]:
    return [
        closes[index] / closes[index - 1] - 1
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return (sum((value - avg) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def normalize(value: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    return clamp((value - lower) / (upper - lower), 0.0, 1.0)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

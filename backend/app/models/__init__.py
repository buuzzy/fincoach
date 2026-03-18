"""Pydantic schemas and SQLAlchemy ORM models."""

from __future__ import annotations
import enum
from datetime import datetime, date
from typing import Optional, Literal
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Enum as SAEnum, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

# Helper: tell SQLAlchemy to store enum .value (lowercase) not .name (UPPERCASE)
_enum_values = lambda x: [e.value for e in x]


# ─── Enums ─────────────────────────────────────────────────────────

class UserProfileType(str, enum.Enum):
    """PRD 四类用户画像"""
    AGGRESSIVE = "aggressive"        # 激进型：频繁交易、追涨杀跌
    CONSERVATIVE = "conservative"    # 保守型：持仓过久、止盈过早
    EMOTIONAL = "emotional"          # 情绪型：追高买入、止损过慢
    BALANCED = "balanced"            # 均衡型：相对理性

class PatternType(str, enum.Enum):
    """5 种核心模式"""
    CHASE_HIGH = "chase_high"            # 追高买入
    EARLY_PROFIT_TAKE = "early_profit"   # 止盈过早
    SLOW_STOP_LOSS = "slow_stop_loss"    # 止损过慢
    OVER_TRADING = "over_trading"        # 频繁交易
    HOLD_TOO_LONG = "hold_too_long"      # 持仓过久

class TradeDirection(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"

class ReportStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


# ─── SQLAlchemy ORM Models ────────────────────────────────────────

class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    profile_type = Column(SAEnum(UserProfileType, values_callable=_enum_values), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    trades = relationship("TradeORM", back_populates="user")
    reports = relationship("ReportORM", back_populates="user")


class TradeORM(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    stock_code = Column(String(20), nullable=False)
    stock_name = Column(String(50), nullable=False)
    direction = Column(SAEnum(TradeDirection, values_callable=_enum_values), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    trade_time = Column(DateTime, nullable=False)
    # 关联卖出时的盈亏（仅卖出方向有值）
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)

    user = relationship("UserORM", back_populates="trades")


class MarketDataORM(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, index=True)
    stock_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(50), nullable=False)
    trade_date = Column(Date, nullable=False, index=True)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    change_pct = Column(Float, nullable=False)


class ReportORM(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(SAEnum(ReportStatus, values_callable=_enum_values), default=ReportStatus.PENDING)
    # JSON 存储完整分析结果
    profile_data = Column(JSON, nullable=True)
    pattern_data = Column(JSON, nullable=True)
    diagnosis_data = Column(JSON, nullable=True)
    backtest_data = Column(JSON, nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_suggestions = Column(Text, nullable=True)
    ai_style_description = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)   # traceback when status=failed
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("UserORM", back_populates="reports")


# ─── Pydantic Schemas ─────────────────────────────────────────────

class TradeRecord(BaseModel):
    id: Optional[int] = None
    user_id: int
    stock_code: str
    stock_name: str
    direction: TradeDirection
    price: float
    quantity: int
    trade_time: datetime
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None

    class Config:
        from_attributes = True


class MarketData(BaseModel):
    stock_code: str
    stock_name: str
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    change_pct: float

    class Config:
        from_attributes = True


class UserProfile(BaseModel):
    user_id: int
    user_name: str
    profile_type: UserProfileType
    trade_count: int
    win_rate: float
    avg_holding_days: float
    total_pnl: float
    avg_pnl_per_trade: float
    max_single_loss: float
    max_single_gain: float
    trade_frequency_per_week: float

    class Config:
        from_attributes = True


class PatternResult(BaseModel):
    pattern_type: PatternType
    pattern_name: str
    occurrences: int
    affected_trades: list[int] = Field(default_factory=list)
    total_impact: float = 0.0  # 该模式导致的总盈亏影响
    description: str = ""
    examples: list[dict] = Field(default_factory=list)
    ai_commentary: str = ""  # LLM 对该 pattern 典型案例的点评


class DiagnosisResult(BaseModel):
    patterns: list[PatternResult]
    primary_issues: list[str]
    severity_score: float  # 0-100
    summary: str
    data_warning: Optional[Literal["insufficient", "preliminary"]] = None


class BacktestScenario(BaseModel):
    name: str
    description: str
    param_change: str
    original_pnl: float
    adjusted_pnl: float
    improvement: float
    improvement_pct: float
    trade_details: list[dict] = Field(default_factory=list)


class BacktestResult(BaseModel):
    scenarios: list[BacktestScenario]
    best_scenario: str
    max_improvement: float


class ReportRequest(BaseModel):
    user_id: int
    period_start: date
    period_end: date


class ReportResponse(BaseModel):
    id: int
    user_id: int
    user_name: str
    period_start: date
    period_end: date
    status: ReportStatus
    profile: Optional[UserProfile] = None
    patterns: Optional[list[PatternResult]] = None
    diagnosis: Optional[DiagnosisResult] = None
    backtest: Optional[BacktestResult] = None
    ai_summary: Optional[str] = None
    ai_suggestions: Optional[str] = None
    ai_style_description: Optional[str] = None
    error_message: Optional[str] = None   # only set when status=failed
    created_at: datetime

    class Config:
        from_attributes = True


class ReportListItem(BaseModel):
    id: int
    user_id: int
    user_name: str
    period_start: date
    period_end: date
    status: ReportStatus
    created_at: datetime
    profile_type: Optional[UserProfileType] = None
    total_pnl: Optional[float] = None
    win_rate: Optional[float] = None
    trade_count: Optional[int] = None

    class Config:
        from_attributes = True


class UserListItem(BaseModel):
    id: int
    name: str
    profile_type: Optional[UserProfileType] = None
    trade_count: int = 0

    class Config:
        from_attributes = True


# ─── Market Data API Schemas ───────────────────────────────────────

class CandleBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataResponse(BaseModel):
    stock_code: str
    stock_name: str
    bars: list[CandleBar]

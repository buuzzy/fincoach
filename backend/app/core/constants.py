"""Shared constants — A股交易手续费参数."""

COMMISSION_RATE = 0.0003          # 佣金 0.03%（买卖双向）
STAMP_DUTY_RATE = 0.001           # 印花税 0.10%（仅卖出）
FEE_DRAG_RATIO_THRESHOLD = 0.20  # 手续费 / 毛利润 > 20% 视为侵蚀


def buy_fee(amount: float) -> float:
    """估算买入手续费：仅佣金。"""
    return amount * COMMISSION_RATE


def sell_fee(amount: float) -> float:
    """估算卖出手续费：佣金 + 印花税。"""
    return amount * (COMMISSION_RATE + STAMP_DUTY_RATE)

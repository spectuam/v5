#!/home/soso/v5/.venv/bin/python3
"""#9 成本层工具：往返 11bp + 分层冲击
往返: 佣金万2.5双边 + 印花税千1(卖出) + 过户费, 简化 11bp
分层冲击: 持仓金额/日均成交额 <1% 无, 1-5% +2bp, >5% +5bp
解耦: 通用成本函数, 供 #12 lowvol 核算及 #11 阶段二回测调用。
"""
ROUND_TRIP_BP = 11  # 往返 11bp


def round_trip_cost():
    """往返成本（买入+卖出）"""
    return ROUND_TRIP_BP / 10000  # 0.0011


def impact_cost(holding_value, avg_amount):
    """分层冲击: 持仓金额 / 日均成交额"""
    if avg_amount <= 0:
        return 0.0
    ratio = holding_value / avg_amount
    if ratio < 0.01:
        return 0.0
    elif ratio < 0.05:
        return 2 / 10000  # 2bp
    else:
        return 5 / 10000  # 5bp


def apply_cost(gross_ret, holding_value, avg_amount):
    """扣往返 + 冲击，返回净收益"""
    return gross_ret - round_trip_cost() - impact_cost(holding_value, avg_amount)

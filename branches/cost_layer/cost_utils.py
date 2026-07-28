#!/home/soso/v5/.venv/bin/python3
"""#9 成本层 v2（完整严谨，§16）
成本分项: 佣金万2.5双边(5bp) + 印花税千0.5(2023.8后卖出,5bp) + 过户费万0.1双边(0.2bp) = 10.2bp
冲击: 平方根模型 impact = c × sqrt(trade_value/daily_amount), c=0.01(经验保守,可校准)
注: 印花税2023.8减半(千1->千0.5), 回测2024+用千0.5; 过户费沪市(深市无,简化双边)
解耦: 通用成本函数, 供 #12 lowvol 核算及 #11 阶段二回测调用。
"""
COMMISSION_BP = 2.5 * 2      # 佣金万2.5双边 = 5bp
STAMP_TAX_BP = 5            # 印花税千0.5(2023.8后,卖出) = 5bp
TRANSFER_FEE_BP = 0.1 * 2    # 过户费万0.1双边(沪市) = 0.2bp
ROUND_TRIP_BP = COMMISSION_BP + STAMP_TAX_BP + TRANSFER_FEE_BP  # 10.2bp
IMPACT_COEF = 0.01          # 平方根冲击系数(经验保守,可校准)


def round_trip_cost():
    """往返成本(买入+卖出)分项"""
    return ROUND_TRIP_BP / 10000  # 0.00102


def impact_cost(trade_value, daily_amount):
    """平方根冲击模型: c × sqrt(trade/daily)
    trade_value: 单笔交易金额(元)
    daily_amount: 日均成交额(元)
    """
    if daily_amount <= 0:
        return 0.0
    ratio = trade_value / daily_amount
    return IMPACT_COEF * (ratio ** 0.5)


def apply_cost(gross_ret, trade_value, daily_amount):
    """扣往返 + 冲击"""
    return gross_ret - round_trip_cost() - impact_cost(trade_value, daily_amount)

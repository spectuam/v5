"""RQAlpha 执行器：tsmom_ls_K12 多头腿每周目标持仓复现

来源: tsmom_ls_K12_holdings.json（自建管道导出，TSMOM信号+top30%持仓）
作用: 验证自写回测 vs RQAlpha 引擎的成交层差异（成本/涨跌停/t+1）
"""
import json
import os
from datetime import datetime


def init(context):
    p = os.path.expanduser('~/v5/branches/compare/tsmom_ls_K12_holdings.json')
    context.holdings = json.load(open(p))['holdings']  # {week: {code: weight}}
    context.last_week = None
    context.n_rebalance = 0


def week_key(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def handle_bar(context, bar_dict):
    wk = week_key(context.now)
    if wk == context.last_week:
        return  # 本周已调仓
    context.last_week = wk
    targets = context.holdings.get(wk, None)
    if targets is None:
        return  # 该周无目标（TSMOM无激活因子）

    # 目标持仓调仓（跳过未上市/不可交易标的）
    n_skip = 0
    for code, w in targets.items():
        try:
            order_target_percent(code, w)
        except Exception:
            n_skip += 1
    # 清仓不在目标中的
    for code in list(context.portfolio.positions.keys()):
        if code not in targets:
            try:
                order_target_percent(code, 0)
            except Exception:
                pass
    if n_skip:
        logger.info(f"@{wk} 跳过不可交易 {n_skip} 只")
    context.n_rebalance += 1
    if context.n_rebalance % 50 == 0:
        logger.info(f"调仓 #{context.n_rebalance} @{wk} 目标{len(targets)}只")

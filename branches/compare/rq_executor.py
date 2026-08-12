"""rq_executor: 通用 RQAlpha 执行器（A2 泛化）

输入: 环境变量 HOLDINGS_PATH -> {week: {code_RQformat: weight}} JSON
      (export_holdings.py 产出, 含 'holdings' 键)
功能: 每周按目标权重调仓, RQAlpha 真实撮合(佣金/印花税/涨跌停/t+1/最小手数)
输出: pkl (由 run_rq.py 配置 sys_analyser.output_file)

泛化自 rq_tsmom_ls.py (DSF, 单策略硬编码 holdings 路径) -> 通用任意持仓.
双层管道第二层: 自写快筛(strategy_factory 毛收益) -> RQAlpha 终审(本文件) -> 四件套

holdings.json 契约:
{
  "strategy": "tsmom_ls_K12",
  "note": "...",
  "holdings": {
    "2016-W03": {"600000.XSHG": 0.02, "000001.XSHE": 0.015, ...},
    ...
  }
}
权重应归一(每周权重和≈1.0); 多头腿策略空头腿纸面(不可成交不列入).
"""
import json
import os


def init(context):
    p = os.environ['HOLDINGS_PATH']
    data = json.load(open(p))
    # 兼容: 顶层即 holdings, 或包在 'holdings' 键下
    context.holdings = data['holdings'] if isinstance(data, dict) and 'holdings' in data else data
    context.last_week = None
    context.n_rebalance = 0
    context.n_skip_total = 0


def week_key(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def handle_bar(context, bar_dict):
    wk = week_key(context.now)
    if wk == context.last_week:
        return  # 本周已调仓
    context.last_week = wk
    targets = context.holdings.get(wk)
    if targets is None:
        return  # 该周无目标持仓

    # 目标持仓调仓(跳过未上市/不可交易标的)
    n_skip = 0
    for code, w in targets.items():
        try:
            order_target_percent(code, w)
        except Exception:
            n_skip += 1
    # 清仓不在目标中的持仓
    for code in list(context.portfolio.positions.keys()):
        if code not in targets:
            try:
                order_target_percent(code, 0)
            except Exception:
                pass
    if n_skip:
        logger.info(f"@{wk} 跳过不可交易 {n_skip} 只")
        context.n_skip_total += n_skip
    context.n_rebalance += 1
    if context.n_rebalance % 50 == 0:
        logger.info(f"调仓 #{context.n_rebalance} @{wk} 目标{len(targets)}只 累计跳过{context.n_skip_total}")

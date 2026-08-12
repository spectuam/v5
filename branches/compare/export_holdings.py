#!/home/soso/v5/.venv/bin/python3
"""export_holdings: 通用持仓导出框架（A2 泛化）

输入: --strategy <name> [策略特定参数]
输出: {strategy, note, holdings: {week: {code_RQformat: weight}}} JSON
      (供 rq_executor.py 消费)

双层管道第一层产出: 自写快筛选策略 -> 本文件导出持仓 -> RQAlpha 终审(rq_executor)

已实现 generator:
- tsmom: TSMOM 信号(K周因子多空均值>0) + top_pct 多头腿
  (复刻 DSF export_tsmom_holdings.py, 参数化 K/TOP_PCT)

待实现 generator (各策略持仓逻辑各异, 按需补, 接口已留):
- daily_pick: strategy_factory rank_and_pick Top5 (需全历史因子预算, 重计算)
- market_eq / lowvol: 从 DB 直接算(轻)
- funnel_*: funnel.py 选因子 + top30%

泛化自 DSF export_tsmom_holdings.py (tsmom_ls_K12 单策略硬编码) -> 通用框架.
空头腿 A 股不可成交, 一律只导多头腿(纸面多空在 candidates_returns 已记录).
"""
import sqlite3, os, json, time
from datetime import datetime
import argparse
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
LS_P = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
START, END = '2016-01-01', '2026-06-30'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def week_key(s):
    iso = datetime.strptime(s[:10], '%Y-%m-%d').isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def code_to_rq(code):
    """sh600000 -> 600000.XSHG ; sz000001 -> 000001.XSHE"""
    if code.startswith('sh'):
        return code[2:] + '.XSHG'
    return code[2:] + '.XSHE'


def gen_tsmom(K=12, top_pct=0.30, name=None):
    """TSMOM 信号多头腿持仓: 过去K周因子多空收益均值>0 -> 选中因子 top_pct 股票等权.
    复刻 export_tsmom_holdings.py 逻辑(DSF), 参数化 K/TOP_PCT."""
    name = name or f'tsmom_K{K}'
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    ls = json.load(open(LS_P))
    log(f"[tsmom] 正交池:{len(orth)}因子 K={K} top_pct={top_pct}")

    db = sqlite3.connect(DB)
    all_dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date", (START, END))]
    week_first = {}
    for d in all_dates:
        wk = week_key(d)
        if wk not in week_first:
            week_first[wk] = d
    weeks = sorted(week_first)
    db.close()
    log(f"[tsmom] 周数:{len(weeks)}")

    fdfs = {}
    for fid in orth:
        fn = fid.replace('/', '_', 1) + '.pkl'
        p = os.path.join(PKL_DIR, fn)
        if not os.path.exists(p):
            continue
        fdf = pd.read_pickle(p)
        fdf.index = fdf.index.astype(str).str[:10]
        fdfs[fid] = fdf
    log(f"[tsmom] 因子缓存:{len(fdfs)}/{len(orth)}")

    holdings = {}
    n_active, n_stocks = [], []
    for i, wk in enumerate(weeks):
        ds = week_first[wk]
        active = []
        for fid in fdfs:
            fls = ls.get(fid, {})
            past = [fls.get(p) for p in weeks[max(0, i - K):i]]
            past = [x for x in past if x is not None]
            if len(past) < K // 2:
                continue
            if np.mean(past) > 0:
                active.append(fid)
        if not active:
            continue
        wts = {}
        for fid in active:
            fdf = fdfs[fid]
            if ds not in fdf.index:
                continue
            vals = fdf.loc[ds].dropna()
            if len(vals) < 30:
                continue
            top = vals.sort_values().iloc[int(len(vals) * (1 - top_pct)):].index
            for c in top:
                wts[c] = wts.get(c, 0.0) + 1.0 / (len(active) * len(top))
        if not wts:
            continue
        holdings[wk] = {code_to_rq(c): round(w, 6) for c, w in wts.items()}
        n_active.append(len(active))
        n_stocks.append(len(wts))
        if (i + 1) % 100 == 0:
            log(f"  {i+1}/{len(weeks)}")

    return {
        "strategy": name, "k": K, "top_pct": top_pct,
        "note": f"TSMOM信号多头腿(空头腿A股不可成交,纸面); K={K} top_pct={top_pct}",
        "holdings": holdings,
        "stats": {"weeks_active": len(holdings), "avg_factors": round(float(np.mean(n_active)), 1) if n_active else 0,
                  "avg_stocks": round(float(np.mean(n_stocks)), 0) if n_stocks else 0},
    }


# 待实现 generator 接口(按需补, 各策略持仓逻辑不同)
def gen_daily_pick(top_k=5, name=None):
    """daily_pick 持仓: strategy_factory rank_and_pick TopN 每周.
    需全历史因子预算(重计算, 碰DB+内存), 复用 strategy_factory.build_panel_history+rank_and_pick.
    TODO: 实现时从 strategy_factory 抽选股逻辑导出 holdings(不算收益)."""
    raise NotImplementedError("daily_pick generator 待实现: 需 strategy_factory 全历史因子预算, 评估内存后补")


def gen_market_eq(name=None):
    """全市场等权多头(轻, 从DB算). TODO."""
    raise NotImplementedError("market_eq generator 待实现")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--strategy', required=True, choices=['tsmom', 'daily_pick', 'market_eq'],
                    help='持仓生成器类型')
    ap.add_argument('--name', help='策略名(默认按类型+参数)')
    ap.add_argument('--k', type=int, default=12, help='tsmom: K周信号')
    ap.add_argument('--top-pct', type=float, default=0.30, help='tsmom: top比例')
    ap.add_argument('--out', help='输出路径(默认 branches/compare/<name>_holdings.json)')
    args = ap.parse_args()

    if args.strategy == 'tsmom':
        result = gen_tsmom(K=args.k, top_pct=args.top_pct, name=args.name)
    elif args.strategy == 'daily_pick':
        result = gen_daily_pick(name=args.name)
    elif args.strategy == 'market_eq':
        result = gen_market_eq(name=args.name)
    else:
        ap.error(f"未知 strategy: {args.strategy}")

    sname = result['strategy']
    out = args.out or os.path.expanduser(f'~/v5/branches/compare/{sname}_holdings.json')
    json.dump(result, open(out, 'w'), ensure_ascii=False)
    st = result.get('stats', {})
    log(f"written: {out}")
    log(f"  活跃周:{st.get('weeks_active', len(result['holdings']))} "
        f"均因子:{st.get('avg_factors', '-')} 均股票:{st.get('avg_stocks', '-')}")


if __name__ == '__main__':
    main()

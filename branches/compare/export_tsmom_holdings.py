#!/home/soso/v5/.venv/bin/python3
"""导出 tsmom_ls_K12 多头腿每周持仓明细 → RQAlpha 执行器用

依据/来源:
- 复刻 collect_heterogeneous.py 的 tsmom_ls 逻辑(TSMOM信号: 过去K周因子多空收益均值>0)
- 复刻 factor_returns_top.py 的 top30% 持仓定义(因子值最大的前30%, 等权)
- 因子值: ~/ading/cache/t3a_factors/*.pkl (日期×股票, 列=sh600000)
- 多空收益: ~/v5/branches/factor_momentum/factor_returns_week.json (TSMOM信号用)
- 只导出多头腿(空头腿A股不可成交, 纸面标注)
输出: ~/v5/branches/compare/tsmom_ls_K12_holdings.json
"""
import sqlite3, os, json, time, gc
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
LS_P = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
OUT = os.path.expanduser('~/v5/branches/compare/tsmom_ls_K12_holdings.json')
K = 12
TOP_PCT = 0.30
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


def main():
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    ls = json.load(open(LS_P))  # {factor: {week: 多空收益}}
    log(f"正交池:{len(orth)}因子, ls周数:{len(list(ls.values())[0]) if ls else 0}")

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
    log(f"周数:{len(weeks)}")

    # 因子值缓存加载 {fid: df(日期×股票)}
    fdfs = {}
    for fid in orth:
        fn = fid.replace('/', '_', 1) + '.pkl'
        p = os.path.join(PKL_DIR, fn)
        if not os.path.exists(p):
            continue
        fdf = pd.read_pickle(p)
        fdf.index = fdf.index.astype(str).str[:10]
        fdfs[fid] = fdf
    log(f"因子缓存:{len(fdfs)}/{len(orth)}")

    # 每周持仓: 多头腿 = TSMOM选中因子的top30%股票, 因子等权, 因子内股票等权
    holdings = {}
    stats = {'weeks_active': 0, 'n_factors_active': [], 'n_stocks': []}
    for i, wk in enumerate(weeks):
        ds = week_first[wk]
        active = []
        # TSMOM 信号: 过去K周 ls 均值 > 0
        for fid in fdfs:
            fls = ls.get(fid, {})
            past = [fls[p] for p in weeks[max(0, i - K):i] if p in fls]
            past = [x for x in past if x is not None]
            if len(past) < K // 2:
                continue
            if np.mean(past) > 0:
                active.append(fid)
        if not active:
            continue
        # 每选中因子取 top30% 股票
        wts = {}
        for fid in active:
            fdf = fdfs[fid]
            if ds not in fdf.index:
                continue
            vals = fdf.loc[ds].dropna()
            if len(vals) < 30:
                continue
            top = vals.sort_values().iloc[int(len(vals) * (1 - TOP_PCT)):].index
            for c in top:
                wts[c] = wts.get(c, 0.0) + 1.0 / (len(active) * len(top))
        if not wts:
            continue
        holdings[wk] = {code_to_rq(c): round(w, 6) for c, w in wts.items()}
        stats['weeks_active'] += 1
        stats['n_factors_active'].append(len(active))
        stats['n_stocks'].append(len(wts))
        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{len(weeks)}")
        del wts

    json.dump({"k": K, "top_pct": TOP_PCT, "note": "多头腿(空头腿A股不可成交,纸面)",
               "holdings": holdings}, open(OUT, 'w'), ensure_ascii=False)
    log(f"written:{OUT} 活跃周:{stats['weeks_active']}/{len(weeks)}, "
        f"平均因子数:{np.mean(stats['n_factors_active']):.1f}, 平均股票数:{np.mean(stats['n_stocks']):.0f}")


if __name__ == '__main__':
    main()

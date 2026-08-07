#!/home/soso/v5/.venv/bin/python3
"""market 等权基准：全市场等权周收益（T+5），作为异构候选(market beta暴露)

复用 factor_returns_top.py 的 t_return + week_rets 逻辑，等权所有股票(不分位)。
输出 market_benchmark_returns.json，合并进 candidates_returns.json。
异构于因子动量(tsmom)：市场beta vs 因子alpha。
"""
import sqlite3, os, json, time
from datetime import datetime
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
OUT = os.path.expanduser('~/v5/branches/compare/market_benchmark_returns.json')
HORIZON = 5
START, END = '2016-01-01', '2026-06-30'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def week_key(s):
    iso = datetime.strptime(s[:10], '%Y-%m-%d').isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def t_return(db, code, date_str, H=HORIZON):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def main():
    log("=" * 60); log("market 等权基准 (全市场等权周收益 T+5)"); log("=" * 60)
    db = sqlite3.connect(DB)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    all_dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date", (START, END)).fetchall()]
    week_first = {}
    for d in all_dates:
        wk = week_key(d)
        if wk not in week_first:
            week_first[wk] = d
    weeks = sorted(week_first)
    log(f"周数:{len(weeks)}, 股票:{len(codes)}")

    log("预算每周全市场T+5等权收益...")
    out = {}
    t0 = time.time()
    for i, wk in enumerate(weeks):
        ds = week_first[wk]
        rets = []
        for code in codes:
            r = t_return(db, code, ds)
            if r is not None:
                rets.append(r)
        if rets:
            out[wk] = float(np.mean(rets))
        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{len(weeks)} [{time.time()-t0:.0f}s]")
    db.close()

    arr = np.array(list(out.values()))
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
    log(f"market等权: {len(out)}周, 全段夏普{sr:.2f}, 年化{arr.mean()*52:.2%}")

    json.dump({'market_eq': [[w, out[w]] for w in sorted(out)]}, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")

    # 合并进 candidates_returns.json
    CAND = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
    cands = json.load(open(CAND))
    cands['market_eq'] = [[w, out[w]] for w in sorted(out)]
    json.dump(cands, open(CAND, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"合并进 candidates_returns.json: {list(cands.keys())}")


if __name__ == '__main__':
    main()

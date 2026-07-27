#!/home/soso/v5/.venv/bin/python3
"""分析 2024 动量失效: 分月动量分位 + 大盘 ret
看动量在哪些月失效 + 是否市场反转(涨多回调)。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
from phase2b_features import build_mkt_cache, log

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
YEAR = '2024'
CUM_W = 30
HORIZON = 10
TOP_K = 10
OUT = '/home/soso/v5/analyze_2024_result.json'


def cum_ret_30(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 31",
        (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 31:
        return None
    rows = rows[::-1]
    return rows[-1][0] / rows[0][0] - 1


def t10_return(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
        (code, date + ' 23:59:59', HORIZON)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < HORIZON:
        return None
    return rows[-1][0] / buy[0] - 1


def main():
    log("=" * 60)
    log(f"分析{YEAR}动量失效")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (YEAR + '-01-01', YEAR + '-12-31')).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"{len(dates)} days, {len(codes)} stocks")

    by_month = {}
    t0 = time.time()
    for di, date in enumerate(dates):
        ds = str(date)[:10]
        month = ds[:7]
        scored = []
        mkt_rets = []
        for code in codes:
            cr = cum_ret_30(code, ds, db)
            if cr is None:
                continue
            r = t10_return(code, ds, db)
            if r is None:
                continue
            scored.append((cr, r))
            mkt_rets.append(r)
        if len(scored) < TOP_K:
            continue
        scored.sort(key=lambda x: -x[0])
        top_rets = [scored[i][1] for i in range(TOP_K)]
        mkt_arr = np.array(mkt_rets)
        for tr in top_rets:
            pct = float((mkt_arr < tr).mean())
            by_month.setdefault(month, {'pcts': [], 'mkt_ret': []})['pcts'].append(pct)
        mkt = mkt_cache.get(ds, {})
        by_month.setdefault(month, {'pcts': [], 'mkt_ret': []})['mkt_ret'].append(mkt.get('mkt_ret', 0))
        if (di + 1) % 30 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log(f"{YEAR} 分月")
    log("=" * 60)
    log(f"{'月':<8} {'动量分位':>8} {'大盘ret':>10} {'n':>5}")
    for m in sorted(by_month):
        d = by_month[m]
        log(f"{m:<8} {np.mean(d['pcts']):.4f} {np.mean(d['mkt_ret'])*100:+.4f}% {len(d['pcts'])}")
    out = {m: {'pct': round(float(np.mean(by_month[m]['pcts'])), 4),
               'mkt_ret': round(float(np.mean(by_month[m]['mkt_ret'])), 5)}
           for m in sorted(by_month)}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

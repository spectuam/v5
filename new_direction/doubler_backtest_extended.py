#!/home/soso/v5/.venv/bin/python3
"""扩展测试期: 纯动量 cum30_h10_t10, 2024-2026, 分年+整体
确认 3 个月的 0.55-0.625 是否稳定。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
from phase2b_features import log

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-07-14'
CUM_W = 30
HORIZON = 10
TOP_K = 10
OUT = '/home/soso/v5/doubler_backtest_extended_result.json'


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
    log(f"扩展测试: cum{CUM_W}_h{HORIZON}_t{TOP_K} {TEST_START}~{TEST_END}")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    by_year = {}
    all_pcts = []
    t0 = time.time()
    for di, date in enumerate(dates):
        ds = str(date)[:10]
        year = ds[:4]
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
            all_pcts.append(pct)
            by_year.setdefault(year, []).append(pct)
        if (di + 1) % 50 == 0:
            log(f"  {di+1}/{len(dates)} overall={np.mean(all_pcts):.4f} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT 扩展测试")
    log("=" * 60)
    log(f"overall avg_pct: {np.mean(all_pcts):.4f} (3个月=0.625/0.553, 目标0.70) n={len(all_pcts)}")
    log("分年:")
    for y in sorted(by_year):
        log(f"  {y}: {np.mean(by_year[y]):.4f} n={len(by_year[y])}")
    out = {'overall': round(float(np.mean(all_pcts)), 4),
           'by_year': {y: round(float(np.mean(by_year[y])), 4) for y in sorted(by_year)},
           'n': len(all_pcts)}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

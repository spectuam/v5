#!/home/soso/v5/.venv/bin/python3
"""纯动量回测: cum_ret_30 排序选 Top5, T+20 收益分位
对比分类器 v1=0.586。若纯动量≈0.586, 分类器无额外贡献, 策略=动量。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
from phase2b_features import log
from doubler_backtest import t20_return

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2026-04-01'
TEST_END = '2026-07-14'
TOP_K = 5
OUT = '/home/soso/v5/doubler_backtest_momentum_result.json'


def cum_ret_30(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 31",
        (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 31:
        return None
    rows = rows[::-1]
    return rows[-1][0] / rows[0][0] - 1


def main():
    log("=" * 60)
    log("纯动量回测: cum_ret_30 排序 Top5")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    daily_pcts = []
    t0 = time.time()
    for di, date in enumerate(dates):
        ds = str(date)[:10]
        scored = []
        mkt_rets = []
        for code in codes:
            cr = cum_ret_30(code, ds, db)
            if cr is None:
                continue
            r = t20_return(code, ds, db)
            if r is None:
                continue
            scored.append((code, cr, r))
            mkt_rets.append(r)
        if len(scored) < TOP_K:
            continue
        scored.sort(key=lambda x: -x[1])
        top_rets = [scored[i][2] for i in range(TOP_K)]
        mkt_arr = np.array(mkt_rets)
        for tr in top_rets:
            daily_pcts.append(float((mkt_arr < tr).mean()))
        if (di + 1) % 10 == 0:
            log(f"  {di+1}/{len(dates)} avg_pct={np.mean(daily_pcts):.4f} [{time.time()-t0:.0f}s]")

    avg_pct = float(np.mean(daily_pcts)) if daily_pcts else 0.0
    log("=" * 60)
    log("RESULT 纯动量")
    log("=" * 60)
    log(f"avg return_percentile: {avg_pct:.4f} (分类器 v1=0.586, 目标>0.70)")
    log(f"n_picks: {len(daily_pcts)}")
    out = {'avg_return_percentile': round(avg_pct, 4), 'classifier_v1': 0.586,
           'n_picks': len(daily_pcts)}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

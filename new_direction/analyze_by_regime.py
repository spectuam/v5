#!/home/soso/v5/.venv/bin/python3
"""分市场状态测动量: 大盘20日累计涨幅分上升/下降/震荡, 分别测动量分位
验证动量趋势期有效(>0.7)、震荡期失效。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
from phase2b_features import build_mkt_cache, log

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-07-14'
HORIZON = 10
TOP_K = 10
TREND_THRESH = 0.02
OUT = '/home/soso/v5/analyze_by_regime_result.json'


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
    log("分市场状态测动量")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    dates_all = sorted(mkt_cache.keys())
    mkt_ret_series = [mkt_cache[d]['mkt_ret'] for d in dates_all]
    # 大盘20日累计涨幅
    mkt_cum20 = {}
    for i in range(20, len(dates_all)):
        cum = 1.0
        for j in range(i - 20, i):
            cum *= (1 + mkt_ret_series[j])
        mkt_cum20[dates_all[i]] = cum - 1

    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks, thresh={TREND_THRESH}")

    by_regime = {'上升': [], '下降': [], '震荡': []}
    t0 = time.time()
    for di, date in enumerate(dates):
        ds = str(date)[:10]
        cum20 = mkt_cum20.get(ds)
        if cum20 is None:
            continue
        if cum20 > TREND_THRESH:
            regime = '上升'
        elif cum20 < -TREND_THRESH:
            regime = '下降'
        else:
            regime = '震荡'
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
            by_regime[regime].append(pct)
        if (di + 1) % 50 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT 分状态")
    log("=" * 60)
    for reg in ['上升', '下降', '震荡']:
        pcts = by_regime[reg]
        if pcts:
            log(f"{reg}: {np.mean(pcts):.4f} n={len(pcts)}")
        else:
            log(f"{reg}: 无样本")
    out = {reg: {'pct': round(float(np.mean(by_regime[reg])), 4) if by_regime[reg] else None,
                'n': len(by_regime[reg])} for reg in by_regime}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

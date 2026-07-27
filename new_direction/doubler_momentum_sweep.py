#!/home/soso/v5/.venv/bin/python3
"""纯动量 sweep: horizon(5/10/20) × TopK(5/10), cum_ret_30 排序
每天算 cum_ret_30 + T+5/10/20 收益, 6组对比分位。baseline T+20 Top5=0.571。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
from phase2b_features import log

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2026-04-01'
TEST_END = '2026-07-14'
HORIZONS = [5, 10, 20]
TOPS = [5, 10]
OUT = '/home/soso/v5/momentum_sweep_result.json'


def cum_ret_30(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 31",
        (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 31:
        return None
    rows = rows[::-1]
    return rows[-1][0] / rows[0][0] - 1


def t_returns(code, date, db, horizons):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
        (code, date + ' 23:59:59', max(horizons))).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < max(horizons):
        return None
    return {h: rows[h - 1][0] / buy[0] - 1 for h in horizons}


def main():
    log("=" * 60)
    log("纯动量 sweep: horizon×TopK")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    results = {(h, t): [] for h in HORIZONS for t in TOPS}
    t0 = time.time()
    for di, date in enumerate(dates):
        ds = str(date)[:10]
        scored = []
        mkt = {h: [] for h in HORIZONS}
        for code in codes:
            cr = cum_ret_30(code, ds, db)
            if cr is None:
                continue
            tr = t_returns(code, ds, db, HORIZONS)
            if tr is None:
                continue
            scored.append((cr, tr))
            for h in HORIZONS:
                mkt[h].append(tr[h])
        if len(scored) < max(TOPS):
            continue
        scored.sort(key=lambda x: -x[0])
        for h in HORIZONS:
            mkt_arr = np.array(mkt[h])
            for t in TOPS:
                top_rets = [scored[i][1][h] for i in range(t)]
                for tr in top_rets:
                    results[(h, t)].append(float((mkt_arr < tr).mean()))
        if (di + 1) % 10 == 0:
            log(f"  {di+1}/{len(dates)} " + " ".join(f"h{h}t{t}={np.mean(results[(h,t)]):.3f}"
                                                     for h in HORIZONS for t in TOPS) + f" [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("SWEEP RESULT")
    log("=" * 60)
    log(f"{'horizon':>8} {'top':>4} {'avg_pct':>8} n")
    for h in HORIZONS:
        for t in TOPS:
            pcts = results[(h, t)]
            log(f"{h:>8} {t:>4} {np.mean(pcts):.4f} {len(pcts)}")
    out = {f'h{h}_t{t}': round(float(np.mean(results[(h, t)])), 4) for h in HORIZONS for t in TOPS}
    json.dump(out, open(OUT, 'w'), indent=2)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

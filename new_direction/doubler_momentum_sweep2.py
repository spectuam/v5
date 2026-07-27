#!/home/soso/v5/.venv/bin/python3
"""纯动量 sweep2: cum_ret窗口(10/20/30) × horizon(3/7/10) × Top(10/20)
扩展调优找最优。baseline T+10 Top10 cum30=0.625。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
from phase2b_features import log

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2026-04-01'
TEST_END = '2026-07-14'
CUM_WINDOWS = [10, 20, 30]
HORIZONS = [3, 7, 10]
TOPS = [10, 20]
MAX_LOOK = 31
OUT = '/home/soso/v5/momentum_sweep2_result.json'


def cum_returns(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT ?",
        (code, date + ' 23:59:59', MAX_LOOK + 1)).fetchall()
    if len(rows) < MAX_LOOK + 1:
        return None
    rows = rows[::-1]
    close = [r[0] for r in rows]
    cr = {}
    for w in CUM_WINDOWS:
        cr[w] = close[-1] / close[-(w + 1)] - 1 if len(close) >= w + 1 else None
    return cr


def t_returns(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
        (code, date + ' 23:59:59', max(HORIZONS))).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < max(HORIZONS):
        return None
    return {h: rows[h - 1][0] / buy[0] - 1 for h in HORIZONS}


def main():
    log("=" * 60)
    log("纯动量 sweep2: cum_ret×horizon×Top")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    results = {(cw, h, t): [] for cw in CUM_WINDOWS for h in HORIZONS for t in TOPS}
    t0 = time.time()
    for di, date in enumerate(dates):
        ds = str(date)[:10]
        scored = []
        mkt = {h: [] for h in HORIZONS}
        for code in codes:
            cr = cum_returns(code, ds, db)
            if cr is None:
                continue
            tr = t_returns(code, ds, db)
            if tr is None:
                continue
            scored.append((cr, tr))
            for h in HORIZONS:
                mkt[h].append(tr[h])
        if len(scored) < max(TOPS):
            continue
        for cw in CUM_WINDOWS:
            sorted_cw = sorted(scored, key=lambda x: -(x[0][cw] if x[0][cw] is not None else -1e9))
            for h in HORIZONS:
                mkt_arr = np.array(mkt[h])
                for t in TOPS:
                    top_rets = [sorted_cw[i][1][h] for i in range(t)]
                    for tr in top_rets:
                        results[(cw, h, t)].append(float((mkt_arr < tr).mean()))
        if (di + 1) % 10 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("SWEEP2 RESULT")
    log("=" * 60)
    log(f"{'cum':>5} {'hor':>4} {'top':>4} {'pct':>8}")
    best = (None, 0.0)
    for cw in CUM_WINDOWS:
        for h in HORIZONS:
            for t in TOPS:
                pcts = results[(cw, h, t)]
                p = float(np.mean(pcts))
                log(f"{cw:>5} {h:>4} {t:>4} {p:.4f}")
                if p > best[1]:
                    best = (f"cum{cw}_h{h}_t{t}", p)
    log(f"BEST: {best[0]} = {best[1]:.4f}")
    out = {f'cum{cw}_h{h}_t{t}': round(float(np.mean(results[(cw, h, t)])), 4)
           for cw in CUM_WINDOWS for h in HORIZONS for t in TOPS}
    out['best'] = best[0]
    out['best_pct'] = round(best[1], 4)
    json.dump(out, open(OUT, 'w'), indent=2)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

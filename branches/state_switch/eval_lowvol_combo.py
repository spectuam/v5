#!/home/soso/v5/.venv/bin/python3
"""低波+反转组合 + 调低波 horizon/Top, 6组对比
1. 低波Top10 T+10 (baseline)
2. 低波Top10 T+5
3. 低波Top10 T+20
4. 低波Top20 T+10
5. 低波Top50 T+10
6. 低波+反转组合 Top10 T+10 (rank合成: 低波低+跌多)
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
OUT = os.path.expanduser('~/v5/branches/state_switch/eval_lowvol_combo_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def vol_20(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21",
        (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 21:
        return None
    closes = [r[0] for r in rows]
    rets = np.diff(closes) / closes[:-1]
    return float(np.std(rets))


def cum_ret_20(code, date, db):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21",
        (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 21:
        return None
    rows = rows[::-1]
    return rows[-1][0] / rows[0][0] - 1


def t_return(code, date, db, H):
    rows = db.execute(
        "SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
        (code, date + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def stats(returns):
    if not returns:
        return None
    arr = np.array(returns)
    arr = np.clip(arr, -0.95, 5.0)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    wr = len(wins) / len(arr) if len(arr) > 0 else 0
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
    pnl = avg_win / avg_loss if avg_loss > 0 else 0
    sharpe = arr.mean() / arr.std() * np.sqrt(252) if arr.std() > 0 else 0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = dd.min() if len(dd) > 0 else 0
    return {
        'win_rate': round(wr, 4), 'pnl_ratio': round(pnl, 4),
        'sharpe': round(sharpe, 4), 'max_dd': round(max_dd, 4),
        'avg_ret': round(arr.mean(), 6), 'n': len(arr),
    }


def main():
    log("=" * 60)
    log("低波+反转组合 + 调horizon/Top, 6组对比")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    # 6组: (label, top, horizon, mode)
    configs = [
        ('lowvol_T10_h10', 10, 10, 'lowvol'),
        ('lowvol_T10_h5', 10, 5, 'lowvol'),
        ('lowvol_T10_h20', 10, 20, 'lowvol'),
        ('lowvol_T20_h10', 20, 10, 'lowvol'),
        ('lowvol_T50_h10', 50, 10, 'lowvol'),
        ('combo_lv+rev_T10_h10', 10, 10, 'combo'),
    ]
    results = {c[0]: [] for c in configs}
    by_year = {c[0]: {} for c in configs}

    t0 = time.time()
    for di, date in enumerate(dates):
        scored = []
        for code in codes:
            v = vol_20(code, date, db)
            cr = cum_ret_20(code, date, db)
            r5 = t_return(code, date, db, 5)
            r10 = t_return(code, date, db, 10)
            r20 = t_return(code, date, db, 20)
            if v is None or cr is None:
                continue
            scored.append((v, cr, code, r5, r10, r20))
        if len(scored) < 50:
            continue

        for label, top, hor, mode in configs:
            rets_field = {5: 3, 10: 4, 20: 5}[hor]  # r5=idx3, r10=4, r20=5
            if mode == 'lowvol':
                sel = sorted(scored, key=lambda x: x[0])[:top]  # vol最低
            elif mode == 'combo':
                # rank合成: vol低(1-rank) + 跌多(1-rank cum_ret)
                import pandas as pd
                df = pd.DataFrame(scored, columns=['vol', 'cr', 'code', 'r5', 'r10', 'r20'])
                df['r_vol'] = 1 - df['vol'].rank(pct=True)
                df['r_rev'] = 1 - df['cr'].rank(pct=True)
                df['combo'] = df['r_vol'] + df['r_rev']
                sel_df = df.sort_values('combo', ascending=False).head(top)
                sel = [(row.vol, row.cr, row.code, row.r5, row.r10, row.r20) for row in sel_df.itertuples()]
            for s in sel:
                r = s[rets_field]
                if r is not None:
                    results[label].append(r)
                    by_year[label].setdefault(date[:4], []).append(r)

        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"{'config':<24} {'夏普':>7} {'盈亏比':>7} {'胜率':>6} {'均收':>9} {'回撤':>8}")
    out = {}
    for label, _, _, _ in configs:
        s = stats(results[label])
        if s:
            log(f"{label:<24} {s['sharpe']:>7.2f} {s['pnl_ratio']:>7.2f} {s['win_rate']:>6.2f} {s['avg_ret']:>9.5f} {s['max_dd']:>8.2f}")
            out[label] = {'overall': s, 'by_year': {y: stats(by_year[label][y]) for y in sorted(by_year[label])}}
    log("(baseline: 低波Top10 T+10 夏普1.87)")
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=str)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

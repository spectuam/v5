#!/home/soso/v5/.venv/bin/python3
"""低波分散: Top50 + 行业分散(每行业最多2只), 对比Top10 baseline
1. 低波Top50 T+20 (分散, 避免集中银行)
2. 低波+行业分散 Top10 T+20 (每行业最多2只, 选10只)
baseline: 低波Top10 T+20 夏普2.65
"""
import sys, os, sqlite3, time, json
from datetime import datetime
from collections import defaultdict
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
HORIZON = 20
OUT = os.path.expanduser('~/v5/branches/state_switch/eval_lowvol_diversify_result.json')


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
    return {'win_rate': round(wr, 4), 'pnl_ratio': round(pnl, 4),
            'sharpe': round(sharpe, 4), 'max_dd': round(max_dd, 4),
            'avg_ret': round(arr.mean(), 6), 'n': len(arr)}


def main():
    log("=" * 60)
    log("低波分散: Top50 + 行业分散, 对比Top10")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    sw2_map = dict(db.execute("SELECT code, sw2_code FROM stock_sw2").fetchall())
    log(f"test {len(dates)} days, {len(codes)} stocks")

    configs = ['lowvol_T10', 'lowvol_T50', 'lowvol_indiv_T10']
    by_year = {c: {} for c in configs}
    all_rets = {c: [] for c in configs}

    t0 = time.time()
    for di, date in enumerate(dates):
        scored = []
        for code in codes:
            v = vol_20(code, date, db)
            r = t_return(code, date, db, HORIZON)
            if v is None or r is None:
                continue
            sw2 = sw2_map.get(code, '?')
            scored.append((v, r, code, sw2))
        if len(scored) < 50:
            continue
        scored.sort(key=lambda x: x[0])  # vol最低在前

        # 1. Top10 baseline
        for i in range(10):
            r = scored[i][1]
            all_rets['lowvol_T10'].append(r)
            by_year['lowvol_T10'].setdefault(date[:4], []).append(r)

        # 2. Top50
        for i in range(min(50, len(scored))):
            r = scored[i][1]
            all_rets['lowvol_T50'].append(r)
            by_year['lowvol_T50'].setdefault(date[:4], []).append(r)

        # 3. 行业分散 Top10 (每行业最多2只)
        ind_count = defaultdict(int)
        indiv_picks = []
        for v, r, code, sw2 in scored:
            if ind_count[sw2] < 2:
                indiv_picks.append(r)
                ind_count[sw2] += 1
                if len(indiv_picks) >= 10:
                    break
        for r in indiv_picks:
            all_rets['lowvol_indiv_T10'].append(r)
            by_year['lowvol_indiv_T10'].setdefault(date[:4], []).append(r)

        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"{'config':<22} {'夏普':>7} {'盈亏比':>7} {'胜率':>6} {'均收':>9} {'回撤':>8}")
    out = {}
    for c in configs:
        s = stats(all_rets[c])
        if s:
            log(f"{c:<22} {s['sharpe']:>7.2f} {s['pnl_ratio']:>7.2f} {s['win_rate']:>6.2f} {s['avg_ret']:>9.5f} {s['max_dd']:>8.2f}")
            out[c] = {'overall': s, 'by_year': {y: stats(by_year[c][y]) for y in sorted(by_year[c])}}
    log("\n分年:")
    for c in configs:
        for y in ['2024', '2025', '2026']:
            s = stats(by_year[c].get(y, []))
            if s:
                log(f"  {c} {y}: 夏普={s['sharpe']} 均收={s['avg_ret']}")
    log("\n(baseline: 低波Top10 T+20 夏普2.65, 2026=-1.27)")
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=str)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

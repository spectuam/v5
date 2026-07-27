#!/home/soso/v5/.venv/bin/python3
"""验证低波Top10 T+20 分年: 2024/2025/2026稳定性
排除2026-07异常。夏普/盈亏比/胜率/max_dd/均收。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
TOP = 10
HORIZON = 20
OUT = os.path.expanduser('~/v5/branches/state_switch/eval_lowvol_h20_result.json')


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
    return {
        'win_rate': round(wr, 4), 'pnl_ratio': round(pnl, 4),
        'sharpe': round(sharpe, 4), 'max_dd': round(max_dd, 4),
        'avg_ret': round(arr.mean(), 6), 'n': len(arr),
    }


def main():
    log("=" * 60)
    log(f"低波Top{TOP} T+{HORIZON} 分年验证 {TEST_START}~{TEST_END}")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    by_year = {}
    all_rets = []
    t0 = time.time()
    for di, date in enumerate(dates):
        scored = []
        for code in codes:
            v = vol_20(code, date, db)
            r = t_return(code, date, db, HORIZON)
            if v is None or r is None:
                continue
            scored.append((v, r))
        if len(scored) < TOP:
            continue
        scored.sort(key=lambda x: x[0])
        for i in range(TOP):
            r = scored[i][1]
            all_rets.append(r)
            by_year.setdefault(date[:4], []).append(r)
        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    overall = stats(all_rets)
    log(f"低波Top{TOP} T+{HORIZON} 全段:")
    log(f"  胜率={overall['win_rate']} 盈亏比={overall['pnl_ratio']} 夏普={overall['sharpe']} 回撤={overall['max_dd']} 均收={overall['avg_ret']} n={overall['n']}")
    log("分年:")
    year_stats = {}
    for y in sorted(by_year):
        s = stats(by_year[y])
        year_stats[y] = s
        log(f"  {y}: 胜率={s['win_rate']} 盈亏比={s['pnl_ratio']} 夏普={s['sharpe']} 回撤={s['max_dd']} 均收={s['avg_ret']} n={s['n']}")
    log("(目标: 夏普>1, 2026是否弱)")
    out = {'overall': overall, 'by_year': year_stats}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

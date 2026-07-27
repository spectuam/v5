#!/home/soso/v5/.venv/bin/python3
"""Step 1: 重算动量/反转盈亏比/夏普
动量 Top10(涨最多) vs 反转 Bottom10(跌最多,过滤ST), 算盈亏比/夏普/胜率/回撤。
2024-2026全段, T+10。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-07-14'
TOP = 10
HORIZON = 10
OUT = os.path.expanduser('~/v5/branches/state_switch/eval_pnl_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


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
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    win_rate = len(wins) / len(arr) if len(arr) > 0 else 0
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
    pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    sharpe = arr.mean() / arr.std() * np.sqrt(252) if arr.std() > 0 else 0
    cum = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = dd.min() if len(dd) > 0 else 0
    return {
        'win_rate': round(win_rate, 4),
        'pnl_ratio': round(pnl_ratio, 4),
        'sharpe': round(sharpe, 4),
        'max_dd': round(max_dd, 4),
        'avg_ret': round(arr.mean(), 6),
        'n': len(arr),
    }


def main():
    log("=" * 60)
    log("Step 1: 动量/反转 盈亏比/夏普")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    momentum_rets = []
    reversal_rets = []
    t0 = time.time()
    for di, date in enumerate(dates):
        scored = []
        for code in codes:
            cr = cum_ret_20(code, date, db)
            if cr is None:
                continue
            r = t_return(code, date, db, HORIZON)
            if r is None:
                continue
            scored.append((cr, r))
        if len(scored) < TOP * 2:
            continue
        scored.sort(key=lambda x: -x[0])
        for i in range(TOP):
            momentum_rets.append(scored[i][1])
        for i in range(1, TOP + 1):
            reversal_rets.append(scored[-i][1])
        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    m = stats(momentum_rets)
    r = stats(reversal_rets)
    log("动量 Top10(涨最多):")
    log(f"  胜率={m['win_rate']} 盈亏比={m['pnl_ratio']} 夏普={m['sharpe']} 回撤={m['max_dd']} 均收={m['avg_ret']} n={m['n']}")
    log("反转 Bottom10(跌最多):")
    log(f"  胜率={r['win_rate']} 盈亏比={r['pnl_ratio']} 夏普={r['sharpe']} 回撤={r['max_dd']} 均收={r['avg_ret']} n={r['n']}")
    log("(目标: 盈亏比>2, 夏普>1)")
    out = {'momentum': m, 'reversal': r}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

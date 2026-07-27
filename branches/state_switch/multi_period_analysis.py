#!/home/soso/v5/.venv/bin/python3
"""多周期切割分析: 周/月/季/半年/年, 每周期内动量/反转/低波表现
看不同周期间最优因子的变化模式, 找启发提策略假设。
因子: 动量Top10(cum_ret_20涨最多), 反转Bottom10(跌最多), 低波Top10(20日std最低)
周期: 周/月/季/半年/年
指标: 均收/胜率/夏普/盈亏比
"""
import sys, os, sqlite3, time, json
from datetime import datetime
from collections import defaultdict
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-07-14'
TOP = 10
HORIZON = 10
OUT = os.path.expanduser('~/v5/branches/state_switch/multi_period_result.json')


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
        return {'win_rate': 0, 'sharpe': 0, 'avg_ret': 0, 'pnl_ratio': 0, 'n': 0}
    arr = np.array(returns)
    arr = np.clip(arr, -0.95, 5.0)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    wr = len(wins) / len(arr) if len(arr) > 0 else 0
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
    pnl = avg_win / avg_loss if avg_loss > 0 else 0
    sharpe = arr.mean() / arr.std() * np.sqrt(252) if arr.std() > 0 else 0
    return {
        'win_rate': round(wr, 4),
        'sharpe': round(sharpe, 4),
        'avg_ret': round(arr.mean(), 6),
        'pnl_ratio': round(pnl, 4),
        'n': len(arr),
    }


def period_key(date_str, granularity):
    y, m, d = int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10])
    if granularity == 'week':
        dt = datetime(y, m, d)
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    elif granularity == 'month':
        return f"{y}-{m:02d}"
    elif granularity == 'quarter':
        return f"{y}-Q{(m - 1) // 3 + 1}"
    elif granularity == 'half':
        return f"{y}-H{'1' if m <= 6 else '2'}"
    elif granularity == 'year':
        return str(y)


def main():
    log("=" * 60)
    log("多周期切割分析: 周/月/季/半年/年 × 动量/反转/低波")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    granularities = ['week', 'month', 'quarter', 'half', 'year']
    factors = ['momentum', 'reversal', 'lowvol']

    # 每天算各因子选股 + 收益
    daily_picks = defaultdict(lambda: defaultdict(list))  # {granularity: {period_key: {factor: [returns]}}}
    # 先按天算, 再分组
    day_results = []  # [(date, factor, return)]
    t0 = time.time()
    for di, date in enumerate(dates):
        scored = []
        for code in codes:
            cr = cum_ret_20(code, date, db)
            v = vol_20(code, date, db)
            r = t_return(code, date, db, HORIZON)
            if cr is None or v is None or r is None:
                continue
            scored.append((cr, v, r))
        if len(scored) < TOP * 2:
            continue
        # 动量 Top10(涨最多)
        mom = sorted(scored, key=lambda x: -x[0])[:TOP]
        # 反转 Bottom10(跌最多)
        rev = sorted(scored, key=lambda x: x[0])[:TOP]
        # 低波 Top10(波动最低)
        low = sorted(scored, key=lambda x: x[1])[:TOP]
        for _, _, r in mom:
            day_results.append((date, 'momentum', r))
        for _, _, r in rev:
            day_results.append((date, 'reversal', r))
        for _, _, r in low:
            day_results.append((date, 'lowvol', r))
        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    # 按周期分组统计
    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    out = {}
    for gran in granularities:
        # {period: {factor: [returns]}}
        periods = defaultdict(lambda: defaultdict(list))
        for date, fac, r in day_results:
            pk = period_key(date, gran)
            periods[pk][fac].append(r)

        # 每周期每因子统计
        log(f"\n=== {gran} ({len(periods)} 段) ===")
        log(f"{'period':<12} {'因子':<10} {'胜率':>6} {'夏普':>7} {'均收':>9} {'盈亏比':>7}")
        best_counts = defaultdict(int)
        all_period_stats = {}
        for pk in sorted(periods):
            best_sharpe = -999
            best_factor = ''
            row = {}
            for fac in factors:
                s = stats(periods[pk][fac])
                row[fac] = s
                log(f"{pk:<12} {fac:<10} {s['win_rate']:>6.2f} {s['sharpe']:>7.2f} {s['avg_ret']:>9.5f} {s['pnl_ratio']:>7.2f}")
                if s['sharpe'] > best_sharpe:
                    best_sharpe = s['sharpe']
                    best_factor = fac
            best_counts[best_factor] += 1
            all_period_stats[pk] = row
        log(f"  最优频次: " + " ".join(f"{f}={best_counts[f]}" for f in factors))
        out[gran] = {'n_periods': len(periods), 'best_counts': dict(best_counts), 'periods': all_period_stats}

    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=str)
    log(f"\nwritten: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

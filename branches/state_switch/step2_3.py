#!/home/soso/v5/.venv/bin/python3
"""Step 2+3: 2026深挖 + 低波分状态回测
1. 大盘20日累计涨幅分状态(上升>2%/下降<-2%/震荡)
2. 低波Top10 T+20 各状态表现
3. 2024/2025/2026 状态分布
4. 分状态回测(上升/震荡用低波, 下降空仓)
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
TOP = 10
HORIZON = 20
TREND_THRESH = 0.02
OUT = os.path.expanduser('~/v5/branches/state_switch/step2_3_result.json')


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


def build_mkt_cache(db):
    rows = db.execute("""
        SELECT date, AVG((close - prev_close)/prev_close) as mkt_ret,
               SUM(CASE WHEN close > prev_close THEN 1.0 ELSE 0 END)/COUNT(*) as up_ratio
        FROM (
            SELECT code, date, close,
                   LAG(close) OVER (PARTITION BY code ORDER BY date) as prev_close
            FROM daily_kline WHERE close > 0 AND code IN (SELECT symbol FROM stock_info WHERE class='stock')
        ) WHERE prev_close IS NOT NULL AND prev_close > 0
        GROUP BY date ORDER BY date
    """).fetchall()
    cache = {}
    rets = [r[1] for r in rows]
    dates_all = [str(r[0])[:10] for r in rows]
    import pandas as pd
    s = pd.Series(rets)
    vol = s.rolling(20).std()
    for i, d in enumerate(dates_all):
        cache[d] = {'mkt_ret': float(rets[i]) if rets[i] else 0,
                    'up_ratio': float(rows[i][2]) if rows[i][2] else 0,
                    'mkt_vol': float(vol.iloc[i]) if not pd.isna(vol.iloc[i]) else 0}
    # 大盘20日累计涨幅
    cum20 = {}
    for i in range(20, len(dates_all)):
        c = 1.0
        for j in range(i - 20, i):
            c *= (1 + rets[j])
        cum20[dates_all[i]] = c - 1
    return cache, cum20


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
    return {'win_rate': round(wr, 4), 'pnl_ratio': round(pnl, 4),
            'sharpe': round(sharpe, 4), 'avg_ret': round(arr.mean(), 6), 'n': len(arr)}


def main():
    log("=" * 60)
    log("Step 2+3: 2026深挖 + 低波分状态回测")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache, mkt_cum20 = build_mkt_cache(db)
    log(f"mkt cache: {len(mkt_cache)} days, cum20: {len(mkt_cum20)}")

    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    # 分状态收集低波收益
    by_regime = {'上升': [], '下降': [], '震荡': []}
    by_regime_year = {'上升': {}, '下降': {}, '震荡': {}}
    # 分状态回测(上升/震荡用低波, 下降空仓=0收益)
    switch_rets = []
    always_rets = []
    year_dist = {y: {'上升': 0, '下降': 0, '震荡': 0} for y in ['2024', '2025', '2026']}

    t0 = time.time()
    for di, date in enumerate(dates):
        cum20 = mkt_cum20.get(date)
        if cum20 is None:
            continue
        if cum20 > TREND_THRESH:
            regime = '上升'
        elif cum20 < -TREND_THRESH:
            regime = '下降'
        else:
            regime = '震荡'
        year = date[:4]
        if year in year_dist:
            year_dist[year][regime] += 1

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
        top_rets = [scored[i][1] for i in range(TOP)]
        avg_top = float(np.mean(top_rets))

        by_regime[regime].extend(top_rets)
        by_regime_year[regime].setdefault(year, []).extend(top_rets)

        # 分状态回测: 上升/震荡用低波, 下降空仓(0)
        always_rets.append(avg_top)
        if regime != '下降':
            switch_rets.append(avg_top)
        else:
            switch_rets.append(0.0)  # 空仓

        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log("\n2024/2025/2026 状态分布:")
    for y in ['2024', '2025', '2026']:
        d = year_dist[y]
        total = sum(d.values())
        log(f"  {y}: 上升={d['上升']}({d['上升']/total*100:.0f}%) 下降={d['下降']}({d['下降']/total*100:.0f}%) 震荡={d['震荡']}({d['震荡']/total*100:.0f}%)")

    log("\n低波Top10 T+20 各状态:")
    for reg in ['上升', '下降', '震荡']:
        s = stats(by_regime[reg])
        if s:
            log(f"  {reg}: 夏普={s['sharpe']} 盈亏比={s['pnl_ratio']} 胜率={s['win_rate']} 均收={s['avg_ret']} n={s['n']}")

    log("\n低波各状态×年份:")
    for reg in ['上升', '下降', '震荡']:
        for y in sorted(by_regime_year[reg]):
            s = stats(by_regime_year[reg][y])
            if s:
                log(f"  {reg} {y}: 夏普={s['sharpe']} 均收={s['avg_ret']} n={s['n']}")

    always_s = stats(always_rets)
    switch_s = stats(switch_rets)
    log(f"\n一直用低波: 夏普={always_s['sharpe']} 盈亏比={always_s['pnl_ratio']} 胜率={always_s['win_rate']} 均收={always_s['avg_ret']}")
    log(f"分状态(下降空仓): 夏普={switch_s['sharpe']} 盈亏比={switch_s['pnl_ratio']} 胜率={switch_s['win_rate']} 均收={switch_s['avg_ret']}")
    log(f"(对比: 低波全段 夏普2.65)")

    out = {'year_dist': year_dist, 'by_regime': {r: stats(by_regime[r]) for r in by_regime},
           'always': always_s, 'switch': switch_s}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=str)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

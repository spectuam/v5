#!/home/soso/v5/.venv/bin/python3
"""深挖2026: 3角度合并
1. 低波因子IC分年(vol_20 vs T+20 Spearman IC)
2. 低波选的票特征(2026 Top10 收盘价/行业)
3. 2026大盘走势 vs 低波收益
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2024-01-01'
TEST_END = '2026-06-30'
HORIZON = 20
OUT = os.path.expanduser('~/v5/branches/state_switch/dig2026_result.json')


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
        SELECT date, AVG((close - prev_close)/prev_close) as mkt_ret
        FROM (
            SELECT code, date, close,
                   LAG(close) OVER (PARTITION BY code ORDER BY date) as prev_close
            FROM daily_kline WHERE close > 0 AND code IN (SELECT symbol FROM stock_info WHERE class='stock')
        ) WHERE prev_close IS NOT NULL AND prev_close > 0
        GROUP BY date ORDER BY date
    """).fetchall()
    return {str(r[0])[:10]: float(r[1]) if r[1] else 0 for r in rows}


def main():
    log("=" * 60)
    log("深挖2026: IC分年 + 选票特征 + 大盘vs低波")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    log(f"mkt cache: {len(mkt_cache)} days")

    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    # 行业映射
    sw2_map = dict(db.execute("SELECT code, sw2_code FROM stock_sw2").fetchall())
    log(f"test {len(dates)} days, {len(codes)} stocks")

    # 1. IC分年
    ic_by_year = {y: [] for y in ['2024', '2025', '2026']}
    # 2. 选票特征(每月1天)
    picks_samples = {}
    # 3. 大盘vs低波
    mkt_vs_lowvol = {y: {'mkt': [], 'lowvol': []} for y in ['2024', '2025', '2026']}

    t0 = time.time()
    for di, date in enumerate(dates):
        year = date[:4]
        vols = []
        rets = []
        pairs = []
        for code in codes:
            v = vol_20(code, date, db)
            r = t_return(code, date, db, HORIZON)
            if v is None or r is None:
                continue
            vols.append(v)
            rets.append(r)
            pairs.append((v, r, code))

        if len(pairs) < 50:
            continue

        # IC
        ic, _ = spearmanr(vols, rets)
        if not np.isnan(ic):
            ic_by_year[year].append(ic)

        # 低波Top10
        pairs.sort(key=lambda x: x[0])
        top10 = pairs[:10]
        top10_avg_ret = float(np.mean([p[1] for p in top10]))
        mkt_ret = mkt_cache.get(date, 0)
        mkt_vs_lowvol[year]['mkt'].append(mkt_ret)
        mkt_vs_lowvol[year]['lowvol'].append(top10_avg_ret)

        # 选票特征(每月1天: date day<=7)
        day = int(date[8:10])
        if day <= 7 and year == '2026':
            picks_samples[date] = []
            for v, r, code in top10:
                close_row = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
                sw2 = sw2_map.get(code, '?')
                picks_samples[date].append({
                    'code': code, 'close': round(close_row[0], 2) if close_row else None,
                    'sw2': sw2, 'vol': round(v, 5), 'ret': round(r, 5)
                })

        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("RESULT")
    log("=" * 60)

    # 1. IC分年
    log("\n1. 低波因子IC分年(vol_20 vs T+20 Spearman):")
    ic_summary = {}
    for y in ['2024', '2025', '2026']:
        ics = ic_by_year[y]
        ic_mean = float(np.mean(ics)) if ics else 0
        ic_summary[y] = {'ic_mean': round(ic_mean, 5), 'n': len(ics)}
        log(f"  {y}: IC={ic_mean:+.5f} n={len(ics)}")
    log("  (IC负=低波->未来涨, IC正=低波->未来跌)")

    # 2. 选票特征
    log("\n2. 2026低波Top10选的票(每月1天样本):")
    for date in sorted(picks_samples.keys()):
        log(f"  {date}:")
        for p in picks_samples[date][:3]:
            log(f"    {p['code']} close={p['close']} sw2={p['sw2']} vol={p['vol']} ret={p['ret']}")
        log(f"    ... (共10只)")

    # 3. 大盘vs低波
    log("\n3. 大盘走势 vs 低波收益(相关):")
    corr_summary = {}
    for y in ['2024', '2025', '2026']:
        mkt = mkt_vs_lowvol[y]['mkt']
        lv = mkt_vs_lowvol[y]['lowvol']
        if len(mkt) > 10:
            corr = float(np.corrcoef(mkt, lv)[0, 1])
            corr_summary[y] = {'corr': round(corr, 4), 'mkt_avg': round(float(np.mean(mkt)), 6),
                              'lv_avg': round(float(np.mean(lv)), 6), 'n': len(mkt)}
            log(f"  {y}: 相关={corr:+.4f} 大盘均收={np.mean(mkt):+.5f} 低波均收={np.mean(lv):+.5f}")
        else:
            log(f"  {y}: 样本不足")

    out = {'ic_by_year': ic_summary, 'picks_samples': picks_samples, 'corr': corr_summary}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=str)
    log(f"\nwritten: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

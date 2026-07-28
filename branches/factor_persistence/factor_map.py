#!/home/soso/v5/.venv/bin/python3
"""factor_map: 每切片最优因子+收益+分位
4因子(低波/反转/动量/融资融券), 月/季/半年/年切片
每切片: 每因子平均收益 + 全市场分位 + 最优因子是谁
存表供横向纵向比较找规律
"""
import sys, os, sqlite3, time, json
from datetime import datetime
from collections import defaultdict
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2015-01-01'
TEST_END = '2026-06-30'
HORIZON = 20
TOP = 10
OUT = os.path.expanduser('~/v5/branches/factor_persistence/factor_map_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def vol_20(code, date, db):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21", (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 21: return None
    closes = [r[0] for r in rows]
    return float(np.std(np.diff(closes) / closes[:-1]))


def cum_ret_20(code, date, db):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21", (code, date + ' 23:59:59')).fetchall()
    if len(rows) < 21: return None
    rows = rows[::-1]
    return rows[-1][0] / rows[0][0] - 1


def rz_buy_ratio(code, date, db):
    row = db.execute("SELECT rz_ye, rz_buy FROM margin_detail WHERE code=? AND date=?", (code, date)).fetchone()
    if not row or row[0] <= 0: return None
    return row[1] / row[0]


def t_return(code, date, db, H):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?", (code, date + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H: return None
    return rows[-1][0] / buy[0] - 1


def period_key(date_str, gran):
    y, m = int(date_str[:4]), int(date_str[5:7])
    if gran == 'week':
        dt = datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]))
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if gran == 'month': return f"{y}-{m:02d}"
    if gran == 'quarter': return f"{y}-Q{(m-1)//3+1}"
    if gran == 'half': return f"{y}-H{'1' if m<=6 else '2'}"
    if gran == 'year': return str(y)


def main():
    log("=" * 60)
    log("factor_map: 每切片最优因子+收益+分位")
    log("=" * 60)
    db = sqlite3.connect(DB)
    dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    factors = {
        'lowvol': {'func': vol_20, 'sort': 'asc'},
        'reversal': {'func': cum_ret_20, 'sort': 'asc'},
        'momentum': {'func': cum_ret_20, 'sort': 'desc'},
        'rz_buy': {'func': rz_buy_ratio, 'sort': 'asc'},
    }
    granularities = ['week', 'month', 'quarter', 'half', 'year']

    # 每天每因子的(收益, 分位)
    daily = {f: defaultdict(list) for f in factors}  # {factor: {date: (ret, pct)}}

    t0 = time.time()
    for di, date in enumerate(dates):
        all_rets = []
        scored = {f: [] for f in factors}
        for code in codes:
            r = t_return(code, date, db, HORIZON)
            if r is None: continue
            all_rets.append(r)
            for fname, fcfg in factors.items():
                v = fcfg['func'](code, date, db)
                if v is not None:
                    scored[fname].append((v, r))
        if len(all_rets) < 10: continue
        all_arr = np.array(all_rets)

        for fname, fcfg in factors.items():
            s = scored[fname]
            if len(s) < 10: continue
            s.sort(key=lambda x: x[0], reverse=(fcfg['sort'] == 'desc'))
            top_rets = [s[i][1] for i in range(min(TOP, len(s)))]
            avg_ret = float(np.mean(top_rets))
            # 分位: top10平均收益在全市场的分位
            pct = float((all_arr < avg_ret).mean())
            daily[fname][date] = (avg_ret, pct)

        if (di + 1) % 100 == 0:
            log(f"  {di+1}/{len(dates)} [{time.time()-t0:.0f}s]")

    # 按切片汇总
    out = {}
    for gran in granularities:
        # {period: {factor: (avg_ret, avg_pct)}}
        periods = defaultdict(lambda: {f: [] for f in factors})
        for fname in factors:
            for date, (ret, pct) in daily[fname].items():
                pk = period_key(date, gran)
                periods[pk][fname].append((ret, pct))

        out[gran] = {}
        log(f"\n=== {gran} ({len(periods)} 段) ===")
        log(f"{'period':<12} {'最优因子':<12} {'收益':>8} {'分位':>7} | 各因子分位")
        for pk in sorted(periods):
            fac_stats = {}
            best_factor = ''
            best_pct = -1
            for fname in factors:
                vals = periods[pk][fname]
                if not vals: continue
                avg_ret = float(np.mean([v[0] for v in vals]))
                avg_pct = float(np.mean([v[1] for v in vals]))
                fac_stats[fname] = {'ret': round(avg_ret, 5), 'pct': round(avg_pct, 4)}
                if avg_pct > best_pct:
                    best_pct = avg_pct
                    best_factor = fname

            out[gran][pk] = {
                'best': best_factor,
                'best_ret': fac_stats[best_factor]['ret'] if best_factor else 0,
                'best_pct': round(best_pct, 4),
                'all': fac_stats,
            }
            pcts_str = " ".join(f"{f}={fac_stats[f]['pct']:.2f}" for f in factors if f in fac_stats)
            log(f"{pk:<12} {best_factor:<12} {fac_stats[best_factor]['ret'] if best_factor else 0:>+8.4f} {best_pct:>7.2f} | {pcts_str}")

    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"\nwritten: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

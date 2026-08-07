#!/home/soso/v5/.venv/bin/python3
"""lowvol 周度版：vol_20 最低 Top10, 周度 T+5 等权

原 eval_lowvol_h20.py 是月度 T+20, 这里改周度 T+5, 和 tsmom 同频进 compare_pool。
复用 market_benchmark 的 t_return + week 逻辑, 加 vol_20 选股。
"""
import sqlite3, os, json, time
from datetime import datetime
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
CAND = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
HORIZON = 5
TOP = 10
START, END = '2016-01-01', '2026-06-30'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def week_key(s):
    iso = datetime.strptime(s[:10], '%Y-%m-%d').isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def t_return(db, code, date_str, H=HORIZON):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def vol_20(db, code, date_str):
    """前20日日收益std"""
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT 21",
                      (code, date_str + ' 23:59:59')).fetchall()
    if len(rows) < 21:
        return None
    closes = np.array([r[0] for r in rows])[::-1]
    rets = np.diff(closes) / closes[:-1]
    return float(np.std(rets)) if len(rets) >= 10 else None


def main():
    log("=" * 60); log("lowvol 周度版 (vol_20最低Top10, T+5等权)"); log("=" * 60)
    db = sqlite3.connect(DB)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    all_dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date", (START, END)).fetchall()]
    week_first = {}
    for d in all_dates:
        wk = week_key(d)
        if wk not in week_first:
            week_first[wk] = d
    weeks = sorted(week_first)
    log(f"周数:{len(weeks)}, 股票:{len(codes)}")

    out = {}
    t0 = time.time()
    for i, wk in enumerate(weeks):
        ds = week_first[wk]
        cand = []
        for code in codes:
            v = vol_20(db, code, ds)
            if v is not None and v > 0:
                r = t_return(db, code, ds)
                if r is not None:
                    cand.append((v, code, r))
        if len(cand) >= TOP:
            cand.sort(key=lambda x: x[0])  # vol升序
            top = cand[:TOP]
            out[wk] = float(np.mean([x[2] for x in top]))
        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{len(weeks)} [{time.time()-t0:.0f}s]")
    db.close()

    arr = np.array(list(out.values()))
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
    log(f"lowvol: {len(out)}周, 全段夏普{sr:.2f}, 年化{arr.mean()*52:.2%}")

    cands = json.load(open(CAND))
    cands['lowvol_weekly'] = [[w, out[w]] for w in sorted(out)]
    json.dump(cands, open(CAND, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"合并进 candidates: {list(cands.keys())}")


if __name__ == '__main__':
    main()

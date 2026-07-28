#!/home/soso/v5/.venv/bin/python3
"""#3 Decile 十分位分组诊断（§6）
每月每因子按因子值分 10 组（D1=因子值最高=看多组），算每组平均 T+20 收益。
看 D1-D10 单调性，定因子用法：D1最好/D2-D3最好D1塌陷/D1-D3差不多/无单调/反向。
训练段 2015-2026。数据：factor pkl + daily_kline。解耦只读。
"""
import sqlite3, os, json, gc, time
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/decile_result.json')
ALL_START, ALL_END = '2015-01-01', '2026-06-30'
HORIZON = 20
N_DECILE = 10


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def t_return(db, code, date_str, H):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def classify_decile(rets):
    """rets: [D1..D10] 平均收益，D1=因子值最高"""
    if len(rets) < N_DECILE:
        return 'insufficient'
    d1, d10 = rets[0], rets[-1]
    best = int(np.argmax(rets))
    if best == 0 and d1 > d10:
        return 'd1_best'           # D1 最好，Top 没问题
    if best in (1, 2) and rets[0] < rets[best]:
        return 'd1_collapse'       # D2/D3 最好，D1 塌陷 -> 剔除 D1 极端
    if max(rets[:3]) - min(rets[:3]) < 0.005:
        return 'd1_d3_flat'        # D1-D3 差不多 -> Top 扩到 D1-D3
    if best == N_DECILE - 1 and d10 > d1:
        return 'd10_best'           # 反向因子（D10 最好）
    return 'non_monotone'


def main():
    log("=" * 60); log("#3 Decile 十分位分组诊断"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池: {len(orth)} 因子, N_DECILE={N_DECILE}")
    db = sqlite3.connect(DB)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    yms = [r[0] for r in db.execute(
        "SELECT DISTINCT substr(date,1,7) ym FROM daily_kline WHERE date>=? AND date<=? ORDER BY 1",
        (ALL_START, ALL_END)).fetchall()]
    month_date = {ym: str(db.execute("SELECT MIN(date) FROM daily_kline WHERE date LIKE ?", (ym + '%',)).fetchone()[0])[:10] for ym in yms}
    log(f"月数: {len(month_date)}")

    # 月度全市场 T+20 收益预算
    log("预算月度全市场 T+20 收益...")
    month_rets = {}
    t0 = time.time()
    for i, (ym, ds) in enumerate(month_date.items()):
        rets = {}
        for code in codes:
            r = t_return(db, code, ds, HORIZON)
            if r is not None:
                rets[code] = r
        month_rets[ym] = rets
        if (i + 1) % 24 == 0:
            log(f"  {i+1}/{len(month_date)} [{time.time()-t0:.0f}s]")

    # 38 因子 decile
    log("算 38 因子 decile...")
    results = {}
    for i, fid in enumerate(orth):
        fn = fid.replace('/', '_', 1) + '.pkl'
        path = os.path.join(PKL_DIR, fn)
        if not os.path.exists(path):
            continue
        fdf = pd.read_pickle(path)
        fdf.index = fdf.index.astype(str).str[:10]
        decile_rets = defaultdict(list)
        for ym, ds in month_date.items():
            if ds not in fdf.index:
                continue
            day_vals = fdf.loc[ds].dropna()
            if len(day_vals) < N_DECILE * 10:
                continue
            sorted_vals = day_vals.sort_values(ascending=False)  # D1=最高
            groups = np.array_split(sorted_vals.index, N_DECILE)
            for gi, gidx in enumerate(groups):
                rets = [month_rets[ym].get(c) for c in gidx]
                rets = [r for r in rets if r is not None]
                if rets:
                    decile_rets[gi + 1].append(float(np.mean(rets)))
        avg = {d: float(np.mean(rs)) for d, rs in decile_rets.items() if rs}
        if len(avg) < N_DECILE:
            results[fid] = {'status': 'insufficient'}
            continue
        rets_list = [avg[d] for d in range(1, N_DECILE + 1)]
        results[fid] = {
            'decile_avg': {str(k): round(v, 5) for k, v in avg.items()},
            'class': classify_decile(rets_list),
            'd1_minus_d10': round(rets_list[0] - rets_list[-1], 5),
        }
        del fdf; gc.collect()
        if (i + 1) % 5 == 0:
            log(f"  {i+1}/{len(orth)} done")

    # 汇总
    classes = defaultdict(list)
    for fid, r in results.items():
        if 'class' in r:
            classes[r['class']].append(fid)
    log("=== 分类 ===")
    for c, facs in classes.items():
        log(f"  {c}: {len(facs)} -> {facs[:8]}")
    for fid in ['gtja191/alpha_016', 'alpha101/alpha_044', 'alpha101/alpha_015']:
        r = results.get(fid, {})
        da = r.get('decile_avg', {})
        log(f"  {fid}: class={r.get('class')} D1={da.get('1')} D10={da.get('10')} D1-D10={r.get('d1_minus_d10')}")

    out = {'run_at': datetime.now().isoformat(), 'period': '2015-2026', 'n_decile': N_DECILE,
           'class_counts': {c: len(v) for c, v in classes.items()}, 'factors': results}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

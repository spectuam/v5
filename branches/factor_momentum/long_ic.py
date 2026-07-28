#!/home/soso/v5/.venv/bin/python3
"""#4 多头端 IC 诊断：因子值 top50 内部 IC vs 全截面 IC
诊断模式（§7 方案A），不设硬门禁。看因子预测力是否在头部（做多拿得到）。
训练段 2015-2022 + 全段 2015-2026。
数据：factor pkl + daily_kline(T20收益) + factor_ic_daily(全截面IC)
解耦：只读，不碰代码。baseline_v0 不动。
"""
import sqlite3, os, json, gc
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/long_ic_result.json')
ALL_START, ALL_END = '2015-01-01', '2026-06-30'
TRAIN_END = '2022-12-31'
TOPN = 50
HORIZON = 20
IC_STRONG = 0.02  # IC 强弱阈值（同 factor_decay_utils）


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def t_return(db, code, date_str, H):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def pkl_filename(aid):
    return aid.replace('/', '_', 1) + '.pkl'


def classify(full_ic, long_ic):
    if full_ic > IC_STRONG and long_ic > IC_STRONG:
        return 'head_strong'      # 头部有真实预测力（主信号候选）
    if full_ic > IC_STRONG and long_ic <= IC_STRONG:
        return 'tail_concentrated'  # 预测力在尾部，做多拿不到
    if full_ic <= IC_STRONG and long_ic > IC_STRONG:
        return 'long_only_strong'   # 全截面弱但头部强
    return 'weak'                    # 都弱


def main():
    log("=" * 60); log("#4 多头端 IC 诊断（top50 vs 全截面）"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池: {len(orth)} 因子, TOPN={TOPN}")
    db = sqlite3.connect(DB)

    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"股票池: {len(codes)}")

    # 月度日期（每月第一个交易日）
    yms = [r[0] for r in db.execute(
        "SELECT DISTINCT substr(date,1,7) ym FROM daily_kline WHERE date>=? AND date<=? ORDER BY 1",
        (ALL_START, ALL_END)).fetchall()]
    month_date = {}
    for ym in yms:
        d = db.execute("SELECT MIN(date) FROM daily_kline WHERE date LIKE ?", (ym + '%',)).fetchone()[0]
        month_date[ym] = str(d)[:10]
    log(f"月数: {len(month_date)}")

    # 每月预算全市场 T+20 收益（top50 复用）
    log("预算月度全市场 T+20 收益...")
    month_rets = {}
    t0 = __import__('time').time()
    for i, (ym, ds) in enumerate(month_date.items()):
        rets = {}
        for code in codes:
            r = t_return(db, code, ds, HORIZON)
            if r is not None:
                rets[code] = r
        month_rets[ym] = rets
        if (i + 1) % 24 == 0:
            log(f"  {i+1}/{len(month_date)} [{__import__('time').time()-t0:.0f}s]")

    # 全截面 IC（factor_ic_daily T20_IC 月均）
    full_ic_monthly = {}
    for fid in orth:
        rows = db.execute("""SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily
            WHERE factor_id=? AND date>=? AND date<=? AND T20_IC IS NOT NULL GROUP BY ym""", (fid, ALL_START, ALL_END)).fetchall()
        full_ic_monthly[fid] = {r[0]: r[1] for r in rows}

    # 38 因子每月 top50 多头端 IC
    log("算 38 因子 top50 多头端 IC...")
    long_ic_monthly = defaultdict(dict)
    for i, fid in enumerate(orth):
        fn = pkl_filename(fid)
        path = os.path.join(PKL_DIR, fn)
        if not os.path.exists(path):
            log(f"  {fid}: pkl 缺失")
            continue
        fdf = pd.read_pickle(path)
        fdf.index = fdf.index.astype(str).str[:10]
        for ym, ds in month_date.items():
            if ds not in fdf.index:
                continue
            day_vals = fdf.loc[ds].dropna()
            if len(day_vals) < TOPN:
                continue
            top = day_vals.nlargest(TOPN)
            common = [c for c in top.index if c in month_rets.get(ym, {})]
            if len(common) < 10:
                continue
            ic, _ = spearmanr(top[common].values, [month_rets[ym][c] for c in common])
            if not np.isnan(ic):
                long_ic_monthly[fid][ym] = float(ic)
        del fdf; gc.collect()
        if (i + 1) % 5 == 0:
            log(f"  {i+1}/{len(orth)} done")

    # 汇总：训练段 2015-2022 + 全段
    log("=" * 60); log("RESULT"); log("=" * 60)
    results = {}
    for fid in orth:
        li = long_ic_monthly.get(fid, {})
        fi = full_ic_monthly.get(fid, {})
        li_train = [v for ym, v in li.items() if ym <= '2022-12']
        li_all = list(li.values())
        fi_train = [v for ym, v in fi.items() if ym <= '2022-12']
        fi_all = list(fi.values())
        if not li_train or not fi_train:
            results[fid] = {'status': 'insufficient_data'}
            continue
        full_train = float(np.mean(fi_train))
        long_train = float(np.mean(li_train))
        full_all = float(np.mean(fi_all)) if fi_all else 0
        long_all = float(np.mean(li_all)) if li_all else 0
        results[fid] = {
            'full_ic_train': round(full_train, 4), 'long_ic_train': round(long_train, 4),
            'full_ic_all': round(full_all, 4), 'long_ic_all': round(long_all, 4),
            'class': classify(full_train, long_train),
            'n_months': len(li_train),
        }

    # 分类汇总
    classes = defaultdict(list)
    for fid, r in results.items():
        if 'class' in r:
            classes[r['class']].append(fid)
    log(f"训练段 2015-2022 分类（IC>{IC_STRONG} 为强）:")
    for c, facs in classes.items():
        log(f"  {c}: {len(facs)} 个 -> {facs[:8]}")
    # 重点：alpha_016/044 多头端如何
    for fid in ['gtja191/alpha_016', 'alpha101/alpha_044', 'alpha101/alpha_015']:
        r = results.get(fid, {})
        log(f"  {fid}: full={r.get('full_ic_train')} long={r.get('long_ic_train')} class={r.get('class')}")

    out = {'run_at': datetime.now().isoformat(), 'topn': TOPN, 'horizon': HORIZON,
           'train': '2015-2022', 'ic_strong': IC_STRONG,
           'class_counts': {c: len(v) for c, v in classes.items()},
           'factors': results}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

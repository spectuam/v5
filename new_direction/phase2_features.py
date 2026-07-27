#!/home/soso/v5/.venv/bin/python3
"""Phase 2: 回溯特征工程

采样 +1(强势)/-1(弱势) 标签各 N, 算 T-10 量价特征, t 检验对比找显著差异。
先用量价(daily_kline 全 2000-2026); 38 因子特征 pkl 只覆盖 2015-2026, 后续可选加。
内存: 采样 2万 × 11 特征, <50MB, 安全。
"""
import sys, os, sqlite3, time
from datetime import datetime
from math import erf, sqrt
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
T_WINDOW = 10
SAMPLE_N = 10000
OUT = '/home/soso/v5/phase2_features_result.json'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def features_for(code, date, db):
    """取 (code, date) 前 T_WINDOW 天量价, 算特征"""
    rows = db.execute("""
        SELECT high, low, close, volume FROM daily_kline
        WHERE code=? AND date < ? AND close>0 ORDER BY date DESC LIMIT ?
    """, (code, date, T_WINDOW)).fetchall()
    if len(rows) < T_WINDOW:
        return None
    rows = rows[::-1]  # 升序
    close = np.array([r[2] for r in rows], float)
    high = np.array([r[0] for r in rows], float)
    low = np.array([r[1] for r in rows], float)
    volume = np.array([r[3] for r in rows], float)
    rets = np.diff(close) / close[:-1]
    if len(rets) < 5:
        return None
    vol_norm = volume / volume.mean() if volume.mean() > 0 else volume
    if len(vol_norm[1:]) == len(rets) and np.std(vol_norm[1:]) > 0:
        vp = float(np.corrcoef(rets, vol_norm[1:])[0, 1])
    else:
        vp = 0.0
    return {
        'cum_ret_10': float(close[-1] / close[0] - 1),
        'mean_ret': float(rets.mean()),
        'ret_std': float(rets.std()),
        'max_up': float(rets.max()),
        'max_dn': float(rets.min()),
        'up_days_ratio': float((rets > 0).mean()),
        'amp_mean': float(((high - low) / close).mean()),
        'vol_change': float(np.diff(volume).mean() / volume[:-1].mean()) if volume[:-1].mean() > 0 else 0.0,
        'ret_1d': float(rets[-1]),
        'ret_3d': float(close[-1] / close[-4] - 1) if len(close) >= 4 else 0.0,
        'vol_price_corr': vp,
    }


def sample_features(label, n, db):
    rows = db.execute(
        "SELECT code, date FROM triple_barrier_labels WHERE label=? ORDER BY RANDOM() LIMIT ?",
        (label, n)).fetchall()
    feats_list = []
    for i, (code, date) in enumerate(rows):
        f = features_for(code, date, db)
        if f:
            f['label'] = label
            feats_list.append(f)
        if (i + 1) % 2000 == 0:
            log(f"  label {label}: {i+1}/{len(rows)}")
    return pd.DataFrame(feats_list)


def main():
    log("=" * 60)
    log(f"Phase 2: 回溯特征 T-{T_WINDOW} 采样{SAMPLE_N}/类")
    log("=" * 60)
    db = sqlite3.connect(DB)
    t0 = time.time()
    log("sampling +1 (强势)...")
    pos = sample_features(1, SAMPLE_N, db)
    log("sampling -1 (弱势)...")
    neg = sample_features(-1, SAMPLE_N, db)
    log(f"pos={len(pos)} neg={len(neg)} [{time.time()-t0:.0f}s]")

    feat_cols = [c for c in pos.columns if c != 'label']
    results = []
    for feat in feat_cols:
        p = pos[feat].dropna()
        n = neg[feat].dropna()
        if len(p) < 10 or len(n) < 10:
            continue
        diff = p.mean() - n.mean()
        se = np.sqrt(p.var() / len(p) + n.var() / len(n))
        t = diff / se if se > 0 else 0
        pval = 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))  # two-tailed 正态近似
        results.append({
            'feat': feat, 'pos_mean': round(p.mean(), 5), 'neg_mean': round(n.mean(), 5),
            'diff': round(diff, 5), 't': round(t, 2), 'pval': round(pval, 6),
            'sig_1pct': pval < 0.01,
        })
    df = pd.DataFrame(results).sort_values('pval')
    log("=" * 60)
    log("FEATURE DIFFERENCES (+1 vs -1, sorted by pval)")
    log("=" * 60)
    log(f"{'feat':<18} {'pos_mean':>10} {'neg_mean':>10} {'diff':>10} {'t':>8} {'pval':>10} sig")
    for _, r in df.iterrows():
        log(f"{r['feat']:<18} {r['pos_mean']:>10} {r['neg_mean']:>10} {r['diff']:>10} "
            f"{r['t']:>8} {r['pval']:>10} {'***' if r['sig_1pct'] else ''}")
    df.to_json(OUT, orient='records', indent=2, force_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

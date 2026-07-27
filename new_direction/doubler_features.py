#!/home/soso/v5/.venv/bin/python3
"""翻倍股特征回溯: 翻倍股 vs 同期非翻倍股, t前量价特征对比
采样翻倍股5000 + 随机非翻5000(同期), 算 t前20/10/30量价+大盘, t检验。
"""
import sys, os, sqlite3, time
from datetime import datetime
from math import erf, sqrt
import numpy as np
import pandas as pd
from phase2b_features import features_for_ext, build_mkt_cache, log

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
SAMPLE = 5000
OUT = '/home/soso/v5/doubler_features_result.json'


def sample_doublers(n, db):
    return db.execute("SELECT code, date FROM doublers ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()


def sample_non_doublers(n, db):
    rows = db.execute("""
        SELECT d.code, d.date FROM daily_kline d
        JOIN stock_info s ON d.code=s.symbol
        WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND d.code NOT LIKE 'bj%'
          AND d.close > 0
          AND NOT EXISTS (SELECT 1 FROM doublers db WHERE db.code=d.code AND db.date=d.date)
        ORDER BY RANDOM() LIMIT ?
    """, (n,)).fetchall()
    return rows


def feats_for(rows, db, mkt_cache, label):
    feats = []
    for i, (code, date) in enumerate(rows):
        f = features_for_ext(code, str(date)[:10], db, mkt_cache)
        if f:
            f['label'] = label
            feats.append(f)
        if (i + 1) % 1000 == 0:
            log(f"  label={label}: {i+1}/{len(rows)}")
    return pd.DataFrame(feats)


def main():
    log("=" * 60)
    log("翻倍股特征回溯: doublers vs non-doublers")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    log("sampling doublers...")
    dbl = sample_doublers(SAMPLE, db)
    log("sampling non-doublers...")
    ndbl = sample_non_doublers(SAMPLE, db)
    log(f"doublers={len(dbl)} non={len(ndbl)}")

    log("features doublers...")
    pos = feats_for(dbl, db, mkt_cache, 1)
    log("features non-doublers...")
    neg = feats_for(ndbl, db, mkt_cache, 0)
    log(f"pos={len(pos)} neg={len(neg)}")

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
        pval = 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))
        results.append({
            'feat': feat, 'dbl_mean': round(p.mean(), 5), 'non_mean': round(n.mean(), 5),
            'diff': round(diff, 5), 't': round(t, 2), 'pval': round(pval, 6), 'sig': pval < 0.01,
        })
    df = pd.DataFrame(results).sort_values('pval')
    log("=" * 60)
    log("FEATURE DIFFERENCES (doublers vs non, sorted by pval)")
    log("=" * 60)
    log(f"{'feat':<22}{'dbl':>10}{'non':>10}{'diff':>10}{'t':>8}{'pval':>10}")
    for _, r in df.iterrows():
        log(f"{r['feat']:<22}{r['dbl_mean']:>10}{r['non_mean']:>10}{r['diff']:>10}"
            f"{r['t']:>8}{r['pval']:>10} {'***' if r['sig'] else ''}")
    df.to_json(OUT, orient='records', indent=2, force_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

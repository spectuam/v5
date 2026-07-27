#!/home/soso/v5/.venv/bin/python3
"""Phase 3a v3: 加 38 因子 + 行业特征

读 38 因子 pkl(当日值) + phase2b 量价/大盘/时间 + 行业(sw2_code), LightGBM AUC。
样本限于 2015-2026 (pkl 覆盖)。内存: 38 pkl ~2.1GB + 其他, 约3GB。
"""
import sys, os, sqlite3, time, json, gc, resource
from datetime import datetime
import numpy as np
import pandas as pd
from phase2b_features import features_for_ext, build_mkt_cache, log
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = '/home/soso/ading/cache/t3a_factors'
TRAIN_END = '2019-01-01'
DATE_START = '2015-01-01'
SAMPLE_POS = 5000
SAMPLE_NEG = 5000
OUT = '/home/soso/v5/phase3a_v3_result.json'


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


def load_factor_pkls():
    fds = {}
    files = sorted(f for f in os.listdir(PKL_DIR) if f.endswith('.pkl'))
    log(f"loading {len(files)} factor pkls...")
    for fn in files:
        parts = fn[:-4].split('_', 1)
        aid = parts[0] + '/' + parts[1]
        fds[aid] = pd.read_pickle(os.path.join(PKL_DIR, fn))
    log(f"  loaded {len(fds)} factors RSS={rss_mb()}MB")
    return fds


def load_sw2_map(db):
    return dict(db.execute("SELECT code, sw2_code FROM stock_sw2").fetchall())


def features_v3(code, date, db, mkt_cache, factor_fds, sw2_map):
    f = features_for_ext(code, date, db, mkt_cache)
    if f is None:
        return None
    ts = pd.Timestamp(date)
    for aid, fdf in factor_fds.items():
        col = 'fac_' + aid.replace('/', '_')
        try:
            if ts in fdf.index and code in fdf.columns:
                v = fdf.at[ts, code]
                f[col] = float(v) if not (v is None or (isinstance(v, float) and np.isnan(v))) else 0.0
            else:
                f[col] = 0.0
        except Exception:
            f[col] = 0.0
    sw2 = sw2_map.get(code, '')
    f['sw2_code'] = float(hash(sw2) % 200) if sw2 else -1.0
    return f


def sample_features(label, is_train, n, db, mkt_cache, factor_fds, sw2_map):
    if is_train:
        rows = db.execute(
            "SELECT code, date FROM triple_barrier_labels "
            "WHERE label=? AND date >= ? AND date < ? ORDER BY RANDOM() LIMIT ?",
            (label, DATE_START, TRAIN_END, n)).fetchall()
    else:
        rows = db.execute(
            "SELECT code, date FROM triple_barrier_labels "
            "WHERE label=? AND date >= ? ORDER BY RANDOM() LIMIT ?",
            (label, TRAIN_END, n)).fetchall()
    feats = []
    for i, (code, date) in enumerate(rows):
        f = features_v3(code, date, db, mkt_cache, factor_fds, sw2_map)
        if f:
            f['label'] = 1 if label == 1 else 0
            feats.append(f)
        if (i + 1) % 2000 == 0:
            log(f"    label {label} {'train' if is_train else 'test'}: {i+1}/{len(rows)}")
    return pd.DataFrame(feats)


def main():
    log("=" * 60)
    log("Phase 3a v3: 加 38 因子 + 行业")
    log("=" * 60)
    db = sqlite3.connect(DB)
    factor_fds = load_factor_pkls()
    mkt_cache = build_mkt_cache(db)
    sw2_map = load_sw2_map(db)
    log(f"RSS={rss_mb()}MB")

    t0 = time.time()
    log("sampling train (2015-2019)...")
    tr_pos = sample_features(1, True, SAMPLE_POS, db, mkt_cache, factor_fds, sw2_map)
    tr_neg = pd.concat([sample_features(0, True, SAMPLE_NEG // 2, db, mkt_cache, factor_fds, sw2_map),
                        sample_features(-1, True, SAMPLE_NEG // 2, db, mkt_cache, factor_fds, sw2_map)])
    train = pd.concat([tr_pos, tr_neg], ignore_index=True)
    log("sampling test (>=2019)...")
    te_pos = sample_features(1, False, SAMPLE_POS, db, mkt_cache, factor_fds, sw2_map)
    te_neg = pd.concat([sample_features(0, False, SAMPLE_NEG // 2, db, mkt_cache, factor_fds, sw2_map),
                        sample_features(-1, False, SAMPLE_NEG // 2, db, mkt_cache, factor_fds, sw2_map)])
    test = pd.concat([te_pos, te_neg], ignore_index=True)
    log(f"train={len(train)} test={len(test)} [{time.time()-t0:.0f}s] RSS={rss_mb()}MB")

    feat_cols = [c for c in train.columns if c != 'label']
    X_tr = train[feat_cols].fillna(0)
    y_tr = train['label']
    X_te = test[feat_cols].fillna(0)
    y_te = test['label']

    log("training LightGBM...")
    model = lgb.LGBMClassifier(n_estimators=100, max_depth=5, learning_rate=0.1, verbose=-1)
    model.fit(X_tr, y_tr)
    proba = model.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(y_te, proba)
    n_top = int(y_te.sum())
    top_idx = np.argsort(proba)[::-1][:n_top]
    precision_top = float(y_te.iloc[top_idx].mean())
    base_rate = float(y_te.mean())

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"AUC: {auc:.4f}  (v1=0.5428, v2=0.5558)")
    log(f"precision@top: {precision_top:.4f} (base {base_rate:.4f}, lift {precision_top/base_rate:.2f}x)")
    log("feature importance (top 15):")
    for f, imp in sorted(zip(feat_cols, model.feature_importances_), key=lambda x: -x[1])[:15]:
        log(f"  {f}: {imp}")

    out = {
        'auc': round(auc, 4), 'precision_top': round(precision_top, 4),
        'base_rate': round(base_rate, 4), 'lift': round(precision_top / base_rate, 2),
        'importance': {f: int(imp) for f, imp in zip(feat_cols, model.feature_importances_)},
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT} RSS={rss_mb()}MB")
    db.close()


if __name__ == '__main__':
    main()

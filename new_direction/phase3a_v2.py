#!/home/soso/v5/.venv/bin/python3
"""Phase 3a v2: 扩展特征分类器有效性

用 Phase 2b 的扩展特征(量价 T-10/20/30 + 大盘 + 时间, 25个)重跑 LightGBM,
看 AUC 能否比 v1(0.54) 提升。有效则进 3b 收益回测。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd
from phase2b_features import features_for_ext, build_mkt_cache, log

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TRAIN_END = '2019-01-01'
SAMPLE_POS = 10000
SAMPLE_NEG = 10000
OUT = '/home/soso/v5/phase3a_v2_result.json'


def sample_features(label, date_op, date_val, n, db, mkt_cache):
    rows = db.execute(
        f"SELECT code, date FROM triple_barrier_labels "
        f"WHERE label=? AND date {date_op} ? ORDER BY RANDOM() LIMIT ?",
        (label, date_val, n)).fetchall()
    feats = []
    for i, (code, date) in enumerate(rows):
        f = features_for_ext(code, date, db, mkt_cache)
        if f:
            f['label'] = 1 if label == 1 else 0
            feats.append(f)
        if (i + 1) % 2000 == 0:
            log(f"    label {label} ({date_op}): {i+1}/{len(rows)}")
    return pd.DataFrame(feats)


def main():
    log("=" * 60)
    log("Phase 3a v2: 扩展特征分类器 (25特征)")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    t0 = time.time()

    log("sampling train (date<2019)...")
    tr_pos = sample_features(1, '<', TRAIN_END, SAMPLE_POS, db, mkt_cache)
    tr_neg0 = sample_features(0, '<', TRAIN_END, SAMPLE_NEG // 2, db, mkt_cache)
    tr_neg1 = sample_features(-1, '<', TRAIN_END, SAMPLE_NEG // 2, db, mkt_cache)
    train = pd.concat([tr_pos, tr_neg0, tr_neg1], ignore_index=True)

    log("sampling test (date>=2019)...")
    te_pos = sample_features(1, '>=', TRAIN_END, SAMPLE_POS, db, mkt_cache)
    te_neg0 = sample_features(0, '>=', TRAIN_END, SAMPLE_NEG // 2, db, mkt_cache)
    te_neg1 = sample_features(-1, '>=', TRAIN_END, SAMPLE_NEG // 2, db, mkt_cache)
    test = pd.concat([te_pos, te_neg0, te_neg1], ignore_index=True)
    log(f"train={len(train)} (pos={len(tr_pos)}) test={len(test)} (pos={len(te_pos)}) [{time.time()-t0:.0f}s]")

    feat_cols = [c for c in train.columns if c != 'label']
    X_tr = train[feat_cols].fillna(0)
    y_tr = train['label']
    X_te = test[feat_cols].fillna(0)
    y_te = test['label']

    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
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
    log(f"AUC: {auc:.4f}  (v1=0.5428)")
    log(f"precision@top: {precision_top:.4f} (base {base_rate:.4f}, lift {precision_top/base_rate:.2f}x)")
    log("feature importance (top 10):")
    for f, imp in sorted(zip(feat_cols, model.feature_importances_), key=lambda x: -x[1])[:10]:
        log(f"  {f}: {imp}")

    out = {
        'auc': round(auc, 4), 'auc_v1': 0.5428,
        'precision_top': round(precision_top, 4),
        'base_rate': round(base_rate, 4),
        'lift': round(precision_top / base_rate, 2),
        'importance': {f: int(imp) for f, imp in zip(feat_cols, model.feature_importances_)},
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

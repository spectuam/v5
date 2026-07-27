#!/home/soso/v5/.venv/bin/python3
"""Phase 3a: 分类器有效性验证

采样训练(date<2019)+测试(date>=2019), 算 T-10 量价特征,
训练 LightGBM 二分类(+1强势 vs 非+1), 评估 AUC + precision@top。
若 precision@top > 19.7%(基线), 分类器有效, 进 Phase 3b 收益回测。
内存: 采样 4万 × 11 特征, <50MB, 安全。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd
from phase2_features import features_for, log

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TRAIN_END = '2019-01-01'
SAMPLE_POS = 10000   # +1 采样
SAMPLE_NEG = 10000   # 非+1 (0/-1 各半)
OUT = '/home/soso/v5/phase3a_classifier_result.json'


def sample_features(label, date_op, date_val, n, db):
    rows = db.execute(f"""
        SELECT code, date FROM triple_barrier_labels
        WHERE label=? AND date {date_op} ? ORDER BY RANDOM() LIMIT ?
    """, (label, date_val, n)).fetchall()
    feats = []
    for i, (code, date) in enumerate(rows):
        f = features_for(code, date, db)
        if f:
            f['label'] = 1 if label == 1 else 0  # +1=正类, 非+1=负类
            feats.append(f)
        if (i + 1) % 2000 == 0:
            log(f"    label {label} ({date_op}): {i+1}/{len(rows)}")
    return pd.DataFrame(feats)


def main():
    log("=" * 60)
    log("Phase 3a: 分类器有效性验证")
    log("=" * 60)
    db = sqlite3.connect(DB)
    t0 = time.time()

    log("sampling train (date<2019)...")
    tr_pos = sample_features(1, '<', TRAIN_END, SAMPLE_POS, db)
    tr_neg0 = sample_features(0, '<', TRAIN_END, SAMPLE_NEG // 2, db)
    tr_neg1 = sample_features(-1, '<', TRAIN_END, SAMPLE_NEG // 2, db)
    train = pd.concat([tr_pos, tr_neg0, tr_neg1], ignore_index=True)

    log("sampling test (date>=2019)...")
    te_pos = sample_features(1, '>=', TRAIN_END, SAMPLE_POS, db)
    te_neg0 = sample_features(0, '>=', TRAIN_END, SAMPLE_NEG // 2, db)
    te_neg1 = sample_features(-1, '>=', TRAIN_END, SAMPLE_NEG // 2, db)
    test = pd.concat([te_pos, te_neg0, te_neg1], ignore_index=True)
    log(f"train={len(train)} (pos={len(tr_pos)}) test={len(test)} (pos={len(te_pos)}) [{time.time()-t0:.0f}s]")

    feat_cols = [c for c in train.columns if c != 'label']
    X_tr = train[feat_cols].fillna(0)
    y_tr = train['label']
    X_te = test[feat_cols].fillna(0)
    y_te = test['label']

    try:
        import lightgbm as lgb
    except ImportError:
        log("lightgbm not installed, installing...")
        os.system(f"{sys.executable} -m pip install lightgbm -q")
        import lightgbm as lgb
    from sklearn.metrics import roc_auc_score

    log("training LightGBM...")
    model = lgb.LGBMClassifier(n_estimators=100, max_depth=5, learning_rate=0.1, verbose=-1)
    model.fit(X_tr, y_tr)

    proba = model.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(y_te, proba)
    # precision@top: 取测试集 top-N (N=测试+1数) 高分股, 看真+1比例
    n_top = int(y_te.sum())
    top_idx = np.argsort(proba)[::-1][:n_top]
    precision_top = float(y_te.iloc[top_idx].mean())
    base_rate = float(y_te.mean())

    log("=" * 60)
    log("RESULT")
    log("=" * 60)
    log(f"AUC: {auc:.4f}")
    log(f"precision@top: {precision_top:.4f} (base rate {base_rate:.4f}, lift {precision_top/base_rate:.2f}x)")
    log("feature importance:")
    for f, imp in sorted(zip(feat_cols, model.feature_importances_), key=lambda x: -x[1]):
        log(f"  {f}: {imp}")

    out = {
        'auc': round(auc, 4),
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

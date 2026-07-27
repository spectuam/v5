#!/home/soso/v5/.venv/bin/python3
"""翻倍股分类器: 翻倍 vs 非翻倍, LightGBM AUC
采样训练(date<2019)+测试(date>=2019) 各 5000+5000, 特征 features_for_ext, AUC。
"""
import sys, os, sqlite3, time, json
from datetime import datetime
import numpy as np
import pandas as pd
from phase2b_features import features_for_ext, build_mkt_cache, log
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TRAIN_END = '2019-01-01'
SAMPLE = 5000
OUT = '/home/soso/v5/doubler_classifier_result.json'


def sample_doublers(date_op, date_val, n, db):
    return db.execute(
        f"SELECT code, date FROM doublers WHERE date {date_op} ? ORDER BY RANDOM() LIMIT ?",
        (date_val, n)).fetchall()


def sample_non_doublers(date_op, date_val, n, db):
    return db.execute(
        f"""SELECT d.code, d.date FROM daily_kline d
        JOIN stock_info s ON d.code=s.symbol
        WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND d.code NOT LIKE 'bj%'
          AND d.close>0 AND d.date {date_op} ?
          AND NOT EXISTS (SELECT 1 FROM doublers db WHERE db.code=d.code AND db.date=d.date)
        ORDER BY RANDOM() LIMIT ?""", (date_val, n)).fetchall()


def feats_for(rows, db, mkt_cache, label):
    feats = []
    for i, (code, date) in enumerate(rows):
        f = features_for_ext(code, str(date)[:10], db, mkt_cache)
        if f:
            f['label'] = label
            feats.append(f)
        if (i + 1) % 2000 == 0:
            log(f"    label={label}: {i+1}/{len(rows)}")
    return pd.DataFrame(feats)


def main():
    log("=" * 60)
    log("翻倍股分类器: doublers vs non")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    t0 = time.time()
    log("sampling train (date<2019)...")
    tr_pos = sample_doublers('<', TRAIN_END, SAMPLE, db)
    tr_neg = sample_non_doublers('<', TRAIN_END, SAMPLE, db)
    log("sampling test (date>=2019)...")
    te_pos = sample_doublers('>=', TRAIN_END, SAMPLE, db)
    te_neg = sample_non_doublers('>=', TRAIN_END, SAMPLE, db)
    log(f"train pos={len(tr_pos)} neg={len(tr_neg)} | test pos={len(te_pos)} neg={len(te_neg)}")

    log("features train pos...")
    trp = feats_for(tr_pos, db, mkt_cache, 1)
    log("features train neg...")
    trn = feats_for(tr_neg, db, mkt_cache, 0)
    train = pd.concat([trp, trn], ignore_index=True)
    log("features test pos...")
    tep = feats_for(te_pos, db, mkt_cache, 1)
    log("features test neg...")
    ten = feats_for(te_neg, db, mkt_cache, 0)
    test = pd.concat([tep, ten], ignore_index=True)
    log(f"train={len(train)} test={len(test)} [{time.time()-t0:.0f}s]")

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
    log(f"AUC: {auc:.4f}")
    log(f"precision@top: {precision_top:.4f} (base {base_rate:.4f}, lift {precision_top/base_rate:.2f}x)")
    log("feature importance (全部, sorted):")
    for f, imp in sorted(zip(feat_cols, model.feature_importances_), key=lambda x: -x[1]):
        log(f"  {f}: {imp}")

    out = {'auc': round(auc, 4), 'precision_top': round(precision_top, 4),
           'base_rate': round(base_rate, 4), 'lift': round(precision_top / base_rate, 2),
           'importance': {f: int(imp) for f, imp in sorted(zip(feat_cols, model.feature_importances_), key=lambda x: -x[1])}}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

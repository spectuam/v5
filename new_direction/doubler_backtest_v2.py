#!/home/soso/v5/.venv/bin/python3
"""翻倍股分类器回测 v2: 调优-选刚启动(cum_ret_30 低+高分)
训练(date<2019), 测试期每天过滤 cum_ret_30 < 当天中位数(没涨太多),
从过滤后选高分 Top5, T+20 收益分位。减涨中偏差。
对比 v1 baseline 0.586。
"""
import sys, os, sqlite3, time, json, gc
from datetime import datetime
import numpy as np
import pandas as pd
from phase2b_features import features_for_ext, build_mkt_cache, log
import lightgbm as lgb
from doubler_backtest import train_model, t20_return

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TEST_START = '2026-04-01'
TEST_END = '2026-07-14'
TOP_K = 5
OUT = '/home/soso/v5/doubler_backtest_v2_result.json'


def main():
    log("=" * 60)
    log("翻倍股回测 v2: 刚启动过滤 (cum_ret_30 < 中位数)")
    log("=" * 60)
    db = sqlite3.connect(DB)
    mkt_cache = build_mkt_cache(db)
    log("training classifier...")
    model, feat_cols = train_model(db, mkt_cache)
    log("trained")

    dates = [r[0] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
        (TEST_START, TEST_END)).fetchall()]
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%'").fetchall()]
    log(f"test {len(dates)} days, {len(codes)} stocks")

    daily_pcts = []
    t0 = time.time()
    for di, date in enumerate(dates):
        ds = str(date)[:10]
        scored = []
        mkt_rets = []
        cum_rets = []
        for code in codes:
            f = features_for_ext(code, ds, db, mkt_cache)
            if not f:
                continue
            r = t20_return(code, ds, db)
            if r is None:
                continue
            x = [f.get(c, 0) for c in feat_cols]
            scored.append((code, x, r))
            mkt_rets.append(r)
            cum_rets.append(f.get('cum_ret_30', 0))
        if len(scored) < TOP_K + 5:
            continue
        # 过滤 cum_ret_30 < 当天中位数(刚启动, 没涨太多)
        cum_median = float(np.median(cum_rets))
        filtered = [(s, cr) for s, cr in zip(scored, cum_rets) if cr < cum_median]
        if len(filtered) < TOP_K:
            filtered = list(zip(scored, cum_rets))  # fallback
        X = pd.DataFrame([f[0][1] for f in filtered], columns=feat_cols)
        proba = model.predict_proba(X)[:, 1]
        top_idx = np.argsort(proba)[::-1][:TOP_K]
        top_rets = [filtered[i][0][2] for i in top_idx]
        mkt_arr = np.array(mkt_rets)
        for tr in top_rets:
            pct = float((mkt_arr < tr).mean())
            daily_pcts.append(pct)
        if (di + 1) % 10 == 0:
            log(f"  {di+1}/{len(dates)} avg_pct={np.mean(daily_pcts):.4f} cum_median={cum_median:.4f} [{time.time()-t0:.0f}s]")

    avg_pct = float(np.mean(daily_pcts)) if daily_pcts else 0.0
    log("=" * 60)
    log("RESULT v2")
    log("=" * 60)
    log(f"avg return_percentile: {avg_pct:.4f} (v1=0.5861, 目标>0.70)")
    log(f"n_picks: {len(daily_picks) if False else len(daily_pcts)}")
    out = {'avg_return_percentile': round(avg_pct, 4), 'v1': 0.5861,
           'n_picks': len(daily_pcts), 'filter': 'cum_ret_30 < median'}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()

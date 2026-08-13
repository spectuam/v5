#!/home/soso/v5/.venv/bin/python3
"""持仓周期测试 — T+1/3/5/10/20 回测对比

验证 Persistent Top 3 因子在长周期持仓时 WR 是否提升。
假设: 因子 T+10/T+20 IC 高于 T+1, 持仓周期匹配后 WR 应上升。
"""
import sys, os, json, gc, warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
import sqlite3
from datetime import datetime
from factor_decay_utils import build_daily_panel
from factor_zoo_adapter import compute_alpha

DB = os.path.expanduser("~/ading/db/stock_data.db")
JSON_PATH = os.path.expanduser("~/ading/data/reports/factor_decay_results.json")
TOP_K = 5
HORIZONS = [1, 3, 5, 10, 20]

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ──── 1. 加载因子 ────
log("Loading factors...")
with open(JSON_PATH) as f:
    data = json.load(f)
ortho = sorted(data['all_orthogonal'], key=lambda x: x['ic_mean'], reverse=True)
# Persistent Top 3
N = data['n_selected']
factor_ids = [f['id'] for f in ortho[:N]]
log(f"  {N} factors: {', '.join(factor_ids)}")

# ──── 2. 面板 + 因子值 ────
log("Building panel + computing factor values...")
panel = build_daily_panel(lookback_days=9999)

factor_dfs = {}
for fid in factor_ids:
    zoo, fname = fid.split('/')
    factor_dfs[fid] = compute_alpha(zoo, fname + '.py', panel)
    gc.collect()

test_dates_all = panel['close'].index[
    (panel['close'].index >= '2026-01-02') & (panel['close'].index <= '2026-07-15')
]
log(f"  {len(test_dates_all)} trading days in test period")

# ──── 3. 逐日选股（因子值只用一次）───
log("Selecting daily Top 5 (once, reused for all horizons)...")

# 预选股：每天选好 Top 5，存起来
daily_picks = []  # list of (dt_str, [code1, code2, code3, code4, code5])

for dt in test_dates_all:
    dt_str = str(dt.date())
    comp = None
    n_factors_used = 0
    for fid, vals in factor_dfs.items():
        if dt in vals.index:
            row = vals.loc[dt]
            p = row.rank(pct=True)
            if n_factors_used == 0:
                comp = p
            else:
                comp = comp + p
            n_factors_used += 1

    if comp is None or n_factors_used == 0:
        continue
    comp = comp / n_factors_used  # 等权平均

    # 涨停过滤
    close_today = panel['close'].loc[dt]
    close_yesterday = panel['close'].shift(1).loc[dt] if len(panel['close'].index) > 1 else None
    if close_yesterday is not None:
        valid = (close_yesterday > 0) & close_today.notna()
        today_gain = (close_today - close_yesterday) / close_yesterday * 100
        valid = valid & (today_gain < 9.8)  # 排除涨停
    else:
        valid = close_today.notna()

    valid_codes = valid.index[valid]
    comp = comp[comp.index.isin(valid_codes)]

    if len(comp.dropna()) < TOP_K:
        continue

    top5 = comp.nlargest(TOP_K)
    daily_picks.append((dt_str, list(top5.index)))

log(f"  {len(daily_picks)} pick days")

# ──── 4. 预加载 kline ────
log("Pre-loading daily_kline for T+N queries...")
db = sqlite3.connect(DB)

# 构建 code → date → close 映射
all_pick_codes = set()
for _, codes in daily_picks:
    all_pick_codes.update(codes)

# 批量加载 sw2 行业映射
sw2_map = {}
for row in db.execute("SELECT code, sw2_code FROM stock_sw2").fetchall():
    sw2_map[row[0]] = row[1]

log(f"  {len(all_pick_codes)} unique stocks, {len(sw2_map)} with industry tags")

# ──── 5. 多周期回测 ────
results_by_horizon = {}

for H in HORIZONS:
    log(f"\n  T+{H}...")
    beats = []
    rets = []

    for dt_str, codes in daily_picks:
        # 每个 pick code 查 T+H 收益
        for code in codes:
            # 买入日收盘
            buy_row = db.execute(
                "SELECT close FROM daily_kline WHERE code=? AND date=?",
                (code, dt_str)
            ).fetchone()
            if not buy_row or buy_row[0] <= 0:
                continue
            buy_price = buy_row[0]

            # T+H 收盘: 按日期排序取第 H 个之后的
            sell_rows = db.execute(
                "SELECT date, close FROM daily_kline WHERE code=? AND date > ? ORDER BY date LIMIT ?",
                (code, dt_str, H)
            ).fetchall()

            if len(sell_rows) < H:
                continue
            sell_price = sell_rows[-1][1]  # 第 H 个交易日收盘
            sell_date = sell_rows[-1][0]

            ret = (sell_price - buy_price) / buy_price * 100
            rets.append(ret)

            # 行业中位数（同日、同行业、同样 H 个交易日）
            sw2 = sw2_map.get(code)
            if not sw2:
                continue
            peers = [r[0] for r in db.execute(
                "SELECT code FROM stock_sw2 WHERE sw2_code=? AND code!=? LIMIT 50",
                (sw2, code)
            ).fetchall()]

            peer_rets = []
            for pc in peers:
                pb = db.execute(
                    "SELECT close FROM daily_kline WHERE code=? AND date=?",
                    (pc, dt_str)
                ).fetchone()
                if not pb or pb[0] <= 0:
                    continue
                ps = db.execute(
                    "SELECT close FROM daily_kline WHERE code=? AND date > ? ORDER BY date LIMIT ?",
                    (pc, dt_str, H)
                ).fetchall()
                if len(ps) < H:
                    continue
                peer_rets.append((ps[-1][0] - pb[0]) / pb[0] * 100)

            if peer_rets:
                med = np.median(peer_rets)
                beats.append(1 if ret > med else 0)

    wr = np.mean(beats) * 100 if beats else 0
    avg_ret = np.mean(rets) if rets else 0

    # 收益分位 (全市场 — 所有非ST票)
    all_market_rets = []
    for dt_str in list(set(p[0] for p in daily_picks[:10]))[:5]:  # 采样5天避免太慢
        for row in db.execute("""
            SELECT d1.code, (d2.close - d1.close)/d1.close*100 as ret
            FROM daily_kline d1
            JOIN daily_kline d2 ON d1.code = d2.code
            WHERE d1.date = ? AND d1.close > 0
              AND d2.date = (SELECT date FROM daily_kline WHERE code=d1.code AND date > d1.date ORDER BY date LIMIT 1 OFFSET ?)
              AND d1.code NOT LIKE 'sz.399%'
              AND d1.code NOT IN (SELECT code FROM stock_info WHERE name LIKE '%ST%')
              AND d2.close IS NOT NULL
        """, (dt_str, H-1)).fetchall():
            all_market_rets.append(row[1])

    results_by_horizon[H] = {
        'wr': round(wr, 1),
        'avg_ret': round(avg_ret, 2),
        'n_picks': len(rets),
        'n_beats': sum(beats),
    }
    log(f"    WR={wr:.1f}%  Avg Ret={avg_ret:+.2f}%  Picks={len(rets)}")

db.close()

# ──── 6. 输出 ────
log(f"\n{'='*65}")
log(f"  持仓周期测试: Persistent Top {N} (vma60 / qtld30 / alpha_040)")
log(f"  测试集: 2026-01-02 ~ 2026-07-13")
log(f"  {'Horizon':<10} {'WR':>8} {'Avg Ret':>10} {'Picks':>8}")
log(f"  {'-'*36}")
for H in HORIZONS:
    r = results_by_horizon[H]
    flag = ""
    if H == 1:
        flag = " (baseline)"
    elif r['wr'] > results_by_horizon[1]['wr'] + 2:
        flag = " ← 提升"
    elif r['wr'] > results_by_horizon[1]['wr']:
        flag = " ↑"
    log(f"  T+{H:<8} {r['wr']:>7.1f}% {r['avg_ret']:>+9.2f}% {r['n_picks']:>8}{flag}")

# 结论
t1_wr = results_by_horizon[1]['wr']
best_H = max(HORIZONS, key=lambda h: results_by_horizon[h]['wr'])
best_wr = results_by_horizon[best_H]['wr']
delta = best_wr - t1_wr

log(f"\n  最佳周期: T+{best_H} (WR={best_wr:.1f}%, vs T+1 {t1_wr:.1f}%, Δ={delta:+.1f}%)")
if best_wr > 55:
    log(f"  ✅ 持仓周期匹配有效 — 因子确实需要更长时间发酵")
elif delta > 2:
    log(f"  △ 有一定提升, 但未突破55%")
else:
    log(f"  ❌ 持仓周期不解决根本问题 — 因子在所有周期表现一致")
log(f"{'='*65}")

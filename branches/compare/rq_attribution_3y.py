#!/home/soso/v5/.venv/bin/python3
"""三年窗口归因闭合：涨跌停贡献 + 停牌贡献

- e8_3y: 1亿, 默认(涨跌停+停牌), 2016-2018
- e8nolimit_3y: 1亿, 无涨跌停, 2016-2018
- 理想: tsmom_ls_K12_long_leg.json 2016-2018 段（无成本无限制）
归因(三年年化):
  涨跌停贡献 = e8_3y - e8nolimit_3y
  费用 = trades 实测/3
  停牌+其余 = e8nolimit_3y - 理想 - 费用
"""
import json, os
import numpy as np
import pandas as pd

BASE = "/home/soso/v5/branches/compare"


def load(tag):
    rq = pd.read_pickle(f"{BASE}/rq_tsmom_ls_result_{tag}.pkl")
    pf = rq["portfolio"]
    pf.index = pd.to_datetime(pf.index)
    trades = rq["trades"]
    return pf, trades


def wk(ts):
    iso = pd.Timestamp(ts).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def weekly_nav(pf):
    s = pf["unit_net_value"]
    w = pd.Series({wk(ts): v for ts, v in s.items()})
    return w / w.iloc[0]


def stats(eq):
    r = eq.pct_change().dropna()
    sr = r.mean() / r.std() * np.sqrt(52) if r.std() > 0 else np.nan
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    ann = eq.iloc[-1] ** (52 / len(eq)) - 1
    return ann, sr, mdd


# 理想口径 2016-2018
ours = json.load(open(f"{BASE}/tsmom_ls_K12_long_leg.json"))
ours_s = pd.Series(ours).sort_index()
start, end = "2016-W01", "2018-W52"
ours_3y = (1 + ours_s[(ours_s.index >= start) & (ours_s.index <= end)]).cumprod()

res = {}
for tag in ["e8_3y", "e8nolimit_3y"]:
    pf, trades = load(tag)
    nav = weekly_nav(pf)
    nav = nav[(nav.index >= start) & (nav.index <= end)]
    nav = nav / nav.iloc[0]
    ann, sr, mdd = stats(nav)
    n = len(trades)
    fee = trades["tax"].sum() + trades["commission"].sum()
    notional = (trades["last_price"] * trades["last_quantity"]).sum()
    res[tag] = {"nav": nav, "ann": ann, "sr": sr, "mdd": mdd,
                "n_trades": n, "fee": fee, "notional": notional}

ann_ideal, sr_ideal, mdd_ideal = stats(ours_3y)

print("=" * 70)
print(f"{'口径':<22} {'年化':>8} {'夏普':>7} {'MDD':>8}  备注")
print("-" * 70)
print(f"{'理想(无成本无限制)':<22} {ann_ideal*100:>7.1f}% {sr_ideal:>7.2f} {mdd_ideal*100:>7.1f}%")
for tag, label in [("e8_3y", "1亿·默认(含涨跌停+停牌)"), ("e8nolimit_3y", "1亿·无涨跌停(仅停牌)")]:
    r = res[tag]
    print(f"{label:<22} {r['ann']*100:>7.1f}% {r['sr']:>7.2f} {r['mdd']*100:>7.1f}%  "
          f"成交{r['n_trades']}笔 费{r['fee']/1e4:.0f}万(本金{r['fee']/1e8*100:.1f}%)")
print("=" * 70)

# 归因（三年年化）——净值已扣费，还原扣费前再分解
ann_e8 = res["e8_3y"]["ann"]
ann_nl = res["e8nolimit_3y"]["ann"]
fee_3y = res["e8_3y"]["fee"] / 1e8 / 3  # 三年年化费用占比(正值)
limit_contrib = ann_e8 - ann_nl          # 涨跌停贡献(负)
susp_contrib = (ann_nl + fee_3y) - ann_ideal  # 停牌+其余 = 无涨跌停扣费前 - 理想(负)

print(f"\n归因分解（三年年化, 理想 {ann_ideal*100:.1f}% → 默认 {ann_e8*100:.1f}%, 缺口 {(ann_ideal-ann_e8)*100:.1f}pp）:")
print(f"  费用:            -{fee_3y*100:.2f}pp  (trades 实测)")
print(f"  涨跌停限制:      {limit_contrib*100:+.2f}pp  (默认 - 无涨跌停)")
print(f"  停牌+其余:       {susp_contrib*100:+.2f}pp  (无涨跌停 - 理想 - 费用)")
print(f"  校验和:          {(-fee_3y+limit_contrib+susp_contrib)*100:+.2f}pp  (应≈缺口 {-(ann_ideal-ann_e8)*100:.2f}pp)")

# 拒绝统计
import re
LOG = "/tmp/claude-1000/-mnt-c-Users-Administrator/5eb22500-6414-49c7-b8d7-b8e4d66f2e23/tasks/bek1q8c2h.output"
up = down = susp = 0
pat_rej = re.compile(r"reach the (limit_up|limit_down) price")
pat_susp = re.compile(r"is suspended")
for line in open(LOG, encoding="utf-8", errors="ignore"):
    m = pat_rej.search(line)
    if m:
        if m.group(1) == "limit_up":
            up += 1
        else:
            down += 1
    elif pat_susp.search(line):
        susp += 1
print(f"\n三年日志拒绝统计: limit_up {up}, limit_down {down}, suspended {susp}")

#!/home/soso/v5/.venv/bin/python3
"""RQAlpha vs 自写回测 对跑对比

- RQAlpha 输出: ~/v5/result.pkl (日度净值, 含佣金/印花税/涨跌停/t+1)
- 我们口径: branches/compare/tsmom_ls_K12_long_leg.json (周频, 无成本/无涨跌停限制)
- 原多空: candidates_returns.json tsmom_ls_K12 (纸面多空)
输出: branches/compare/rq_compare_report.html
"""
import json, os, sys
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

BASE = "/home/soso/v5/branches/compare"


def week_key(ts):
    iso = pd.Timestamp(ts).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def main(pkl_path):
    # RQAlpha 日度净值
    rq = pd.read_pickle(pkl_path)
    if isinstance(rq, dict):
        # sys_analyser 新版输出 dict
        key = "portfolio" if "portfolio" in rq else list(rq.keys())[0]
        df = rq[key]
    else:
        df = rq
    # 找净值列
    col = None
    for c in ["unit_net_value", "net_value", "total_value"]:
        if c in df.columns:
            col = c
            break
    if col is None:
        print("RQAlpha 列:", list(df.columns))
        return
    rq_nav = df[col]
    rq_nav.index = pd.to_datetime(rq_nav.index)

    # 周聚合
    rq_weekly = {}
    for ts, v in rq_nav.items():
        wk = week_key(ts)
        rq_weekly[wk] = float(v)
    rq_weekly = pd.Series(rq_weekly)

    # 我们口径多头腿
    ours = json.load(open(f"{BASE}/tsmom_ls_K12_long_leg.json"))
    ours_s = pd.Series(ours)
    ours_eq = (1 + ours_s).cumprod()

    # 原多空（纸面）
    cands = json.load(open(f"{BASE}/candidates_returns.json"))
    ls_raw = pd.Series({r[0]: r[1] for r in cands["tsmom_ls_K12"]})
    ls_eq = (1 + ls_raw).cumprod()

    # 对齐到 RQAlpha 的周索引（我们序列有预热期缺失，reindex 后从首个非空截断）
    common = rq_weekly.index
    rq_eq = rq_weekly[common]
    ours_a = ours_eq.reindex(common)
    ls_a = ls_eq.reindex(common)
    start = ours_a.first_valid_index()
    common = common[common >= start]
    rq_eq = rq_eq[common]
    rq_eq = rq_eq / rq_eq.iloc[0]
    ours_eq = ours_a[common]
    ls_eq = ls_a[common]

    # 指标
    def stats(eq, freq=52):
        r = eq.pct_change().dropna()
        sr = r.mean() / r.std() * np.sqrt(freq) if r.std() > 0 else np.nan
        mdd = (eq / np.maximum.accumulate(eq) - 1).min()
        return sr, mdd

    sr_rq, mdd_rq = stats(rq_eq)
    sr_ours, mdd_ours = stats(ours_eq[common])
    sr_ls, mdd_ls = stats(ls_eq[common])
    ann_rq = rq_eq.iloc[-1] ** (52 / len(rq_eq)) - 1
    ann_ours = ours_eq[common].iloc[-1] ** (52 / len(ours_eq[common])) - 1
    ann_ls = ls_eq[common].iloc[-1] ** (52 / len(ls_eq[common])) - 1

    print("=" * 70)
    print(f"{'口径':<20} {'年化':>8} {'夏普':>7} {'MDD':>8}  说明")
    print("-" * 70)
    print(f"{'RQAlpha 多头腿':<20} {ann_rq*100:>7.1f}% {sr_rq:>7.2f} {mdd_rq*100:>7.1f}%  含佣金/印花税/涨跌停/t+1")
    print(f"{'我们 多头腿':<20} {ann_ours*100:>7.1f}% {sr_ours:>7.2f} {mdd_ours*100:>7.1f}%  无成本/无涨跌停限制")
    print(f"{'原 多空(纸面)':<20} {ann_ls*100:>7.1f}% {sr_ls:>7.2f} {mdd_ls*100:>7.1f}%  纸面多空,不可成交")
    print("=" * 70)

    # 图
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rq_eq.index, y=rq_eq.values, name="RQAlpha 多头腿(含成本/涨跌停)", line=dict(color="#d62728", width=2)))
    fig.add_trace(go.Scatter(x=ours_eq[common].index, y=(ours_eq[common] / ours_eq[common].iloc[0]).values,
                             name="我们口径多头腿(理想)", line=dict(color="#1f77b4", width=2)))
    fig.add_trace(go.Scatter(x=ls_eq[common].index, y=(ls_eq[common] / ls_eq[common].iloc[0]).values,
                             name="原多空(纸面)", line=dict(color="#888", width=1.2, dash="dash")))
    fig.update_layout(title="RQAlpha vs 自写回测：tsmom_ls_K12 多头腿净值对比",
                      xaxis_title="周", yaxis_title="净值(起点=1)", height=520, hovermode="x unified")
    html = pio.to_html(fig, include_plotlyjs=True, full_html=False)
    with open(f"{BASE}/reports/rq_compare_report.html", "w", encoding="utf-8") as f:
        f.write(f"<html><head><meta charset='utf-8'><title>对跑对比</title></head><body>{html}</body></html>")
    print("报告: branches/compare/reports/rq_compare_report.html")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/v5/result.pkl"))

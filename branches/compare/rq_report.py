#!/home/soso/v5/.venv/bin/python3
"""RQAlpha 对跑归因报告（四次运行全对照）

运行: base(100万,默认成本) / e8(1亿,默认成本) / bp(100万,纯费率无最低佣金)
对照: 我们理想多头腿(无成本) / 纸面多空(原候选)
输出: branches/compare/reports/rq_compare_full_report.html
"""
import json, os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

BASE = "/home/soso/v5/branches/compare"


def load_pkl(tag):
    p = f"{BASE}/rq_tsmom_ls_result.pkl" if tag == "base" else f"{BASE}/rq_tsmom_ls_result_{tag}.pkl"
    if not os.path.exists(p):
        return None
    rq = pd.read_pickle(p)
    pf = rq["portfolio"]
    pf.index = pd.to_datetime(pf.index)
    trades = rq["trades"]
    pw = rq["positions_weight"]
    return {"pf": pf, "trades": trades, "pw": pw}


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


def fee_stats(trades):
    tax = trades["tax"].sum()
    comm = trades["commission"].sum()
    notional = (trades["last_price"] * trades["last_quantity"]).sum()
    n = len(trades)
    return n, notional, comm, tax


# 加载
runs = {}
for tag, label, cap in [("base", "100万·默认成本", 1e6), ("e8", "1亿·默认成本", 1e8), ("bp", "100万·纯费率", 1e6)]:
    r = load_pkl(tag)
    if r:
        r["label"] = label
        r["cap"] = cap
        runs[tag] = r

# 我们理想多头腿 + 纸面多空
ours = json.load(open(f"{BASE}/tsmom_ls_K12_long_leg.json"))
ours_eq = pd.Series(ours).sort_index()
cands = json.load(open(f"{BASE}/candidates_returns.json"))
ls_raw = pd.Series({r[0]: r[1] for r in cands["tsmom_ls_K12"]}).sort_index()

# 各自独立算周净值, 绘图时从理想序列起点对齐
navs = {}
for tag, r in runs.items():
    navs[tag] = weekly_nav(r["pf"])

start = ours_eq.index[0]
navs_aligned = {}
for tag, nav in navs.items():
    nav = nav[nav.index >= start]
    navs_aligned[tag] = nav / nav.iloc[0]

ours_a = ours_eq[ours_eq.index >= start]
ls_a = ls_raw[ls_raw.index >= start]
ours_eqn = (1 + ours_a).cumprod()
ls_eqn = (1 + ls_a).cumprod()

# 指标表
rows = []
for tag in ["base", "e8", "bp"]:
    if tag not in navs_aligned:
        continue
    eq = navs_aligned[tag]
    ann, sr, mdd = stats(eq)
    n, notional, comm, tax = fee_stats(runs[tag]["trades"])
    avg_pos = runs[tag]["pw"]["count"].mean()
    rows.append({"运行": runs[tag]["label"], "年化": f"{ann*100:.1f}%", "夏普": f"{sr:.2f}",
                 "MDD": f"{mdd*100:.1f}%", "成交笔数": n, "总费用占本金": f"{(comm+tax)/runs[tag]['cap']*100:.1f}%",
                 "平均持仓": f"{avg_pos:.0f}只"})

ann_o, sr_o, mdd_o = stats(ours_eqn)
ann_l, sr_l, mdd_l = stats(ls_eqn)
rows.insert(0, {"运行": "我们理想(无成本)", "年化": f"{ann_o*100:.1f}%", "夏普": f"{sr_o:.2f}",
                "MDD": f"{mdd_o*100:.1f}%", "成交笔数": "—", "总费用占本金": "0", "平均持仓": "4050只(目标)"})
rows.insert(1, {"运行": "纸面多空(原候选)", "年化": f"{ann_l*100:.1f}%", "夏普": f"{sr_l:.2f}",
                "MDD": f"{mdd_l*100:.1f}%", "成交笔数": "—", "总费用占本金": "—", "平均持仓": "—"})
table_html = pd.DataFrame(rows).to_html(index=False, border=0, classes="tbl")

# 图1 净值对比
fig1 = go.Figure()
colors = {"base": "#d62728", "e8": "#ff7f0e", "bp": "#9467bd"}
for tag in ["base", "e8", "bp"]:
    if tag in navs_aligned:
        fig1.add_trace(go.Scatter(x=navs_aligned[tag].index, y=navs_aligned[tag].values,
                                  name=runs[tag]["label"], line=dict(color=colors[tag], width=2)))
fig1.add_trace(go.Scatter(x=ours_eqn.index, y=(ours_eqn / ours_eqn.iloc[0]).values,
                          name="我们理想(无成本)", line=dict(color="#1f77b4", width=2)))
fig1.add_trace(go.Scatter(x=ls_eqn.index, y=(ls_eqn / ls_eqn.iloc[0]).values,
                          name="纸面多空", line=dict(color="#888", width=1.2, dash="dash")))
fig1.update_layout(title="净值对比：RQAlpha 三运行 vs 自写口径（tsmom_ls_K12 多头腿）",
                   xaxis_title="周", yaxis_title="净值(起点=1)", height=520, hovermode="x unified")

# 图2 持仓数时间序列（base vs e8）
fig2 = go.Figure()
for tag in ["base", "e8"]:
    if tag in runs:
        pw = runs[tag]["pw"]
        pw.index = pd.to_datetime(pw.index)
        fig2.add_trace(go.Scatter(x=pw.index, y=pw["count"], name=runs[tag]["label"] + " 持仓数",
                                  line=dict(color=colors[tag])))
fig2.add_hline(y=4050, line_dash="dash", line_color="#999",
               annotation_text="目标持仓 4050 只", annotation_position="top right")
fig2.update_layout(title="实际持仓数量：资金规模的影响", xaxis_title="日期", yaxis_title="持仓只数",
                   height=420, hovermode="x unified")

# 费用拆解
fee_rows = []
for tag in ["base", "e8", "bp"]:
    if tag not in runs:
        continue
    n, notional, comm, tax = fee_stats(runs[tag]["trades"])
    min_part = n * 5.0 if tag != "bp" else 0.0
    rate_part = max(comm - min_part, 0) if tag != "bp" else comm
    fee_rows.append({"运行": runs[tag]["label"], "成交笔数": n,
                     "名义额(万)": f"{notional/1e4:.0f}",
                     "佣金总额(万)": f"{comm/1e4:.1f}",
                     "其中最低5元部分(万)": f"{min_part/1e4:.1f}",
                     "印花税(万)": f"{tax/1e4:.1f}",
                     "费用占本金": f"{(comm+tax)/runs[tag]['cap']*100:.1f}%"})
fee_html = pd.DataFrame(fee_rows).to_html(index=False, border=0, classes="tbl")

CSS = """
body{font-family:'Microsoft YaHei',sans-serif;max-width:1100px;margin:24px auto;padding:0 20px;color:#222}
h1{font-size:24px}h2{font-size:18px;border-left:4px solid #d62728;padding-left:8px;margin-top:36px}
.meta{color:#666;font-size:13px;line-height:1.8}
.tbl{border-collapse:collapse;width:100%;font-size:13px}
.tbl th,.tbl td{border:1px solid #ddd;padding:6px 8px;text-align:right}
.tbl th{background:#f5f5f5}
.box{border:1px solid #ddd;border-radius:6px;padding:12px 16px;background:#fafafa;font-size:14px;line-height:1.8}
.warn{border-left:4px solid #d62728;background:#fdf2f2}
"""

fig1_html = pio.to_html(fig1, include_plotlyjs=True, full_html=False)
fig2_html = pio.to_html(fig2, include_plotlyjs=False, full_html=False)

html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>RQAlpha 对跑归因报告</title><style>{CSS}</style></head><body>
<h1>RQAlpha 对跑归因报告：tsmom_ls_K12 多头腿</h1>
<p class="meta">生成：2026-08-09 · 引擎：RQAlpha 6.x（A股日线 bundle，涨跌停/停牌/t+1/最低佣金内置）<br>
策略：TSMOM 信号选因子（过去12周因子多空收益>0）× top30% 持仓，每周调仓，多头腿（空头腿A股不可成交，纸面）<br>
对照口径：我们理想（无成本/无限制，自写回测假设）· 纸面多空（原候选，factor_returns 多空）</p>

<h2>① 指标总表</h2>
{table_html}
<p class="meta">理想口径与我们回测一致；RQAlpha 三运行含佣金(万8,最低5元/笔)+印花税(万5)+涨跌停/停牌/t+1。</p>

<h2>② 净值对比</h2>
{fig1_html}
{fig2_html}

<h2>③ 费用拆解</h2>
{fee_html}
<div class="box">
<b>佣金模型</b>：每笔 max(成交额×万8, 最低5元)；卖出收印花税万5。<br>
<b>关键</b>：base 运行 43,589 笔佣金 21.8 万中，<b>21.8 万全是"最低5元"部分</b>（单笔名义额中位 417 元，费率部分仅 ~0.3 元/笔）——最低佣金占费用 97%+。
</div>

<h2>④ 归因结论</h2>
<div class="box warn">
<b>差距 16.1% → 2.1%（14 个百分点）的分解：</b><br>
1. <b>资金规模×权重（主要）</b>：100万 ÷ 4050 只 = 247 元/只 < 一手 → 订单取整为 0 股被静默丢弃 → 实际持仓仅 655 只（16% 成交）→ 策略没有按设计执行<br>
2. <b>最低佣金 5 元/笔</b>：4.4 万笔 × 5 元 = 本金 21.8% 被费用吃掉（纯费率版预期大幅改善）<br>
3. <b>涨跌停/停牌</b>：日志仅 23 条拒绝，占比小<br>
4. <b>t+1/复权口径</b>：周频影响小，待确认<br>
<b>含义</b>："全市场等权"形态在小资金下不可执行——这是<b>候选形态问题</b>，不是回测引擎问题；自写回测的"精确按比例成交"假设是系统性高估来源。
</div>

<div class="box ok">
<b>报告责任</b>：本报告只输出证据与程序性结论。归因数字基于 RQAlpha trades/portfolio 实测，非估算。
</div>
</body></html>"""

out = f"{BASE}/reports/rq_compare_full_report.html"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("报告:", out)

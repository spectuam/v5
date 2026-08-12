# -*- coding: utf-8 -*-
"""v5 候选池口径探索原型（streamlit 本地应用）

口径可调项（真实重算）：时间窗口 / 候选集 / 是否显示基准
口径固定项（数据限制，诚实标注）：周频 / 成本=compare_pool 原口径 / CPCV 划分
成本档位：需策略层输出换手序列后支持（当前标注不可调）

运行: .venv/bin/streamlit run branches/compare/explore_pool.py
数据: candidates_returns.json + compare_pool_result.json (8/8 01:05)
"""
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import date as dtdate

BASE = "/home/soso/v5/branches/compare"

NAMES = {
    "daily_pick_eqcomposite_top5": "daily_pick 等权Top5（生产）",
    "market_eq": "全市场等权（基准）",
    "tsmom_ls_K12": "TSMOM 多空 K12",
    "tsmom_long_K12": "TSMOM 做多 K12",
    "funnel_top5_eq_ls": "漏斗Top5 多空",
    "funnel_top5_eq_long": "漏斗Top5 做多",
    "funnel_top5_tsmom_long": "漏斗Top5+TSMOM 做多",
    "tsmom_long_K1": "TSMOM 做多 K1",
    "tsmom_long_K4": "TSMOM 做多 K4",
    "tsmom_long_K24": "TSMOM 做多 K24",
    "eq38_ls": "38因子等权 多空",
    "lowvol_weekly": "低波周频",
    "phase2_ic_weekly": "phase2 IC周频",
}
COLORS = {k: "#888" for k in NAMES}
COLORS["daily_pick_eqcomposite_top5"] = "#d62728"
COLORS["market_eq"] = "#000000"


@st.cache_data
def load():
    def parse(w):
        y, wk = int(w.split("-W")[0]), int(w.split("-W")[1])
        return dtdate.fromisocalendar(y, wk, 1)
    cr = json.load(open(f"{BASE}/candidates_returns.json"))
    df = pd.DataFrame({k: pd.Series({parse(r[0]): r[1] for r in v}).sort_index()
                       for k, v in cr.items()}).ffill()
    df.index = pd.to_datetime(df.index)  # date 对象 → DatetimeIndex
    return df, cr


df, cr = load()
all_keys = [k for k in cr if k != "market_eq"]
mkt = df["market_eq"]

st.set_page_config(page_title="v5 口径探索", layout="wide")
st.title("v5 候选池 · 口径探索（原型）")
st.caption("目标：调口径看敏感性。**可调**：时间窗口/候选集/基准显示。**固定（诚实标注）**：周频、成本=compare_pool 原口径、CPCV 划分。成本档位需换手数据接入后支持。")

with st.sidebar:
    st.header("口径设置")
    sel = st.multiselect("候选策略", all_keys,
                         default=["tsmom_ls_K12", "funnel_top5_eq_ls",
                                  "daily_pick_eqcomposite_top5", "tsmom_long_K12"])
    y0, y1 = st.slider("时间窗口（年）", 2016, 2026, (2016, 2026))
    show_mkt = st.checkbox("显示市场等权基准", value=True)
    cost_note = st.caption("⚠ 成本档位暂不可调：缺策略换手序列，待策略层接入")
    st.divider()
    st.caption("口径固定项：周频再平衡 · 年化√52 · 成本=compare_pool原口径(6bps级) · 后复权日线")

mask = (df.index.year >= y0) & (df.index.year <= y1)
sub = df[mask]
if sub.empty:
    st.warning("该时间窗口无数据")
    st.stop()

shown = list(sel) + (["market_eq"] if show_mkt else [])

# ---- 图1 净值曲线 ----
fig = go.Figure()
for k in shown:
    eq = (1 + sub[k]).cumprod()
    fig.add_trace(go.Scatter(
        x=eq.index, y=eq.values, name=NAMES.get(k, k), mode="lines",
        line=dict(color=COLORS.get(k, "#888"),
                  width=3 if k == "market_eq" else (2.5 if k == "daily_pick_eqcomposite_top5" else 1.5))))
fig.update_layout(title=f"净值曲线（{y0}~{y1}，起点=1）", height=480, hovermode="x unified")
fig.update_xaxes(autorange=True)
fig.update_yaxes(autorange=True)
# key 随口径变化 → 强制重挂载，清掉上次的放大/缩放残留
st.plotly_chart(fig, use_container_width=True, key=f"eq_{y0}_{y1}_{'-'.join(sorted(sel))}")

# ---- 指标表（窗口内重算） ----
rows = []
for k in shown:
    r = sub[k]
    sr = r.mean() / r.std() * np.sqrt(52) if r.std() > 0 else np.nan
    eqc = (1 + r).cumprod()
    dd = (eqc / eqc.cummax() - 1).min()
    beta = r.cov(mkt) / mkt.var() if mkt.var() > 0 else np.nan
    alpha = (r.mean() - beta * mkt.mean()) * 52
    calmar = (r.mean() * 52) / abs(dd) if dd != 0 else np.nan
    rows.append({"策略": NAMES.get(k, k), "窗口年化收益": f"{r.mean()*52*100:.1f}%",
                 "夏普": f"{sr:.2f}", "最大回撤": f"{dd*100:.1f}%", "Calmar": f"{calmar:.2f}",
                 "beta": f"{beta:.2f}", "年化alpha": f"{alpha*100:.1f}%"})
st.subheader("窗口内指标（真实重算）")
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ---- 图2 alpha/beta 四象限 ----
fig2 = go.Figure()
for k in shown:
    r = sub[k]
    beta = r.cov(mkt) / mkt.var() if mkt.var() > 0 else np.nan
    alpha = (r.mean() - beta * mkt.mean()) * 52
    fig2.add_trace(go.Scatter(
        x=[beta], y=[alpha * 100], mode="markers+text", name=NAMES.get(k, k),
        text=[NAMES.get(k, k).split("（")[0]], textposition="top center", textfont=dict(size=10),
        marker=dict(size=12, color=COLORS.get(k, "#888")),
        hovertemplate=f"<b>{NAMES.get(k, k)}</b><br>beta={beta:.2f}<br>年化alpha={alpha*100:.1f}%<extra></extra>"))
fig2.add_hline(y=0, line_color="#999", line_dash="dash")
fig2.add_vline(x=0, line_color="#999", line_dash="dash")
fig2.update_layout(title=f"alpha/beta 归因（{y0}~{y1} 窗口内重算）", height=480,
                   xaxis_title="beta（市场敞口）", yaxis_title="年化 alpha（%）",
                   xaxis=dict(range=[-0.3, 1.3]), yaxis=dict(range=[-15, 20]), showlegend=False)
fig2.update_xaxes(autorange=False)  # 四象限固定坐标系，不缩放
fig2.update_yaxes(autorange=False)
st.plotly_chart(fig2, use_container_width=True, key=f"ab_{y0}_{y1}_{'-'.join(sorted(sel))}")

st.caption("依据/来源：candidates_returns.json + compare_pool_result.json（8/8 01:05，CPCV/MCS/DSR 方法见 compare_pool.py）。本页为口径探索工具，非证据固化——出报告时口径固定并显式记录。")

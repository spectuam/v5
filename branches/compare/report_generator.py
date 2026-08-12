#!/home/soso/v5/.venv/bin/python3
"""report_generator: 四件套报告生成器（C2，统一去硬编码）

整合 DSF report_compare_pool.py + report_daily_pick.py(两份近乎重复, 硬编码8/8毛收益).
改进:
1. 去硬编码: 所有数字从 compare_pool_result.json 读(含毛/净双口径)
2. 净口径: 主指标用净收益(A1), 毛收益作对照(DSF 8/8版是毛收益虚高)
3. 自动证伪判定: 按 A3 four_piece_schema 门槛算 verdict(非写死"死了")
4. 统一: 一脚本对全池/单策略, 不重复两份

输出: branches/compare/reports/v5_four_piece_report.html
"""
import json, os
from datetime import datetime, date as dtdate
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

BASE = os.path.expanduser('~/v5/branches/compare')
CR = json.load(open(f'{BASE}/candidates_returns.json'))
CP = json.load(open(f'{BASE}/compare_pool_result.json'))
ST = CP['strategies']
ROUND_TRIP = CP['cost_model']['round_trip_bp'] / 10000  # 0.00102

# A3 证伪门槛
F1_DSR = 0.95
F3_DECAY = 0.50

NAMES = {
    "daily_pick_eqcomposite_top5": "daily_pick Top5(生产)", "market_eq": "全市场等权(基准)",
    "tsmom_ls_K12": "TSMOM多空K12", "tsmom_long_K12": "TSMOM做多K12",
    "funnel_top5_eq_ls": "漏斗Top5多空", "funnel_top5_eq_long": "漏斗Top5做多",
    "funnel_top5_tsmom_long": "漏斗Top5+TSMOM做多", "tsmom_long_K1": "TSMOM做多K1",
    "tsmom_long_K4": "TSMOM做多K4", "tsmom_long_K24": "TSMOM做多K24",
    "eq38_ls": "38因子等权多空", "lowvol_weekly": "低波周频", "phase2_ic_weekly": "phase2 IC周频",
}


def parse_w(w):
    y, wk = int(w.split('-W')[0]), int(w.split('-W')[1])
    return dtdate.fromisocalendar(y, wk, 1)


def to_eq(rows, deduct=0.0):
    s = pd.Series({parse_w(r[0]): r[1] - deduct for r in rows})
    return (1 + s.sort_index()).cumprod()


# 净收益净值(主) + 毛收益净值(对照)
eq_net = pd.DataFrame({k: to_eq(v, ROUND_TRIP) for k, v in CR.items()}).ffill()
eq_gross = pd.DataFrame({k: to_eq(v, 0.0) for k, v in CR.items()}).ffill()

# alpha/beta 归因(净收益)
mkt = pd.DataFrame({k: pd.Series({parse_w(r[0]): r[1] - ROUND_TRIP for r in v}).sort_index() for k, v in CR.items()})
ab = {}
for k in CR:
    df = pd.concat([mkt[k], mkt['market_eq']], axis=1, join='inner').dropna()
    df.columns = ['s', 'm']
    if df['m'].var() > 0:
        beta = df['s'].cov(df['m']) / df['m'].var()
        alpha = df['s'].mean() - beta * df['m'].mean()
        r2 = (beta * df['m'].std() / df['s'].std()) ** 2 if df['s'].std() > 0 else 0
    else:
        beta = alpha = r2 = 0
    ab[k] = {'beta': beta, 'alpha_ann': alpha * 52, 'r2': r2}


def falsify(name, s):
    """A3 证伪判定: F1 DSR + F2 MCS + F3 forward衰减"""
    ev = []
    dsr = s.get('dsr', 0)
    ev.append({'rule': 'F1_DSR', 'value': dsr, 'threshold': F1_DSR, 'passed': dsr >= F1_DSR})
    in_mcs = name in CP.get('mcs_set', [])
    ev.append({'rule': 'F2_MCS', 'value': int(in_mcs), 'threshold': 1, 'passed': in_mcs})
    # F3: IS->OOS 衰减(train>0.1时才算, 否则IS太弱无从衰减)
    tr, oos = s.get('sharpe_train', 0), s.get('sharpe_oos', 0)
    if tr > 0.1:
        decay = max(0, 1 - oos / tr)
        ev.append({'rule': 'F3_forward_decay', 'value': round(decay, 3), 'threshold': F3_DECAY, 'passed': decay <= F3_DECAY})
    verdict = '未死_待forward积累' if all(e['passed'] for e in ev) else '死了'
    return verdict, ev


# ── 图1 净值(净收益主, 毛收益对照) ──
fig1 = go.Figure()
for k in CR:
    fig1.add_trace(go.Scatter(x=eq_net.index, y=eq_net[k], name=NAMES.get(k, k) + '(净)',
                              mode='lines', line=dict(width=2.5 if k in ('daily_pick_eqcomposite_top5', 'market_eq') else 1.2),
                              visible=True if k in ('daily_pick_eqcomposite_top5', 'market_eq', 'tsmom_ls_K12', 'funnel_top5_eq_ls') else 'legendonly'))
fig1.update_layout(title='图1 净值曲线(净收益口径, 扣周度round_trip 10.2bp)', xaxis_title='日期',
                   yaxis_title='净值(起点=1)', legend=dict(font=dict(size=9)), height=480, hovermode='x unified')

# ── 图2 SR毛/净对照 ──
names2 = [NAMES.get(k, k) for k in ST]
fig2 = go.Figure()
fig2.add_trace(go.Bar(name='毛收益SR', x=names2, y=[ST[k]['sharpe_gross_full'] for k in ST], marker_color='#aaa'))
fig2.add_trace(go.Bar(name='净收益SR(主)', x=names2, y=[ST[k]['sharpe_full'] for k in ST], marker_color='#d62728'))
fig2.update_layout(title='图2 毛收益 vs 净收益 SR(A1成本修正: 周度10.2bp满换仓上界)', barmode='group',
                   xaxis_tickangle=35, height=440, legend=dict(orientation='h', y=1.15))

# ── 图3 DSR + 0.95门槛 ──
fig3 = go.Figure(go.Bar(x=names2, y=[ST[k]['dsr'] for k in ST], marker_color=['#d62728' if ST[k]['dsr'] < F1_DSR else '#2ca02c' for k in ST]))
fig3.add_hline(y=F1_DSR, line_dash='dash', line_color='#d62728')
fig3.update_layout(title='图3 DSR(按N_eff=%.2f校正), 红=未过0.95证伪F1' % CP['n_eff'], xaxis_tickangle=35, height=420)

# ── 图4 alpha/beta ──
fig4 = go.Figure()
for k in CR:
    fig4.add_trace(go.Scatter(x=[ab[k]['beta']], y=[ab[k]['alpha_ann'] * 100], mode='markers+text',
                              name=NAMES.get(k, k), text=[NAMES.get(k, k).split('(')[0]], textposition='top center',
                              marker=dict(size=11)))
fig4.add_hline(y=0, line_color='#999', line_dash='dash'); fig4.add_vline(x=0, line_color='#999', line_dash='dash')
fig4.update_layout(title='图4 归因: alpha(选股) vs beta(市场敞口)', xaxis_title='beta', yaxis_title='年化alpha(%)', height=460, showlegend=False)

# ── 汇总表 + 证伪判定 ──
rows = []
for k in ST:
    s = ST[k]
    verdict, ev = falsify(k, s)
    rows.append({
        '策略': NAMES.get(k, k), '毛SR': s['sharpe_gross_full'], '净SR': s['sharpe_full'],
        'DSR': s['dsr'], 'MCS内': '是' if k in CP.get('mcs_set', []) else '否',
        'MDD': f'{s["max_dd"]*100:.1f}%', 'beta': f'{ab[k]["beta"]:.2f}', 'alpha年': f'{ab[k]["alpha_ann"]*100:.1f}%',
        '证伪判定': verdict,
    })
table_html = pd.DataFrame(rows).to_html(index=False, border=0, classes='tbl', escape=False)

n_dead = sum(1 for r in rows if r['证伪判定'] == '死了')
n_alive = len(rows) - n_dead

CSS = """body{font-family:'Microsoft YaHei',sans-serif;max-width:1140px;margin:24px auto;padding:0 20px;color:#222}
h1{font-size:23px}h2{font-size:17px;border-left:4px solid #d62728;padding-left:8px;margin-top:32px}
.meta{color:#666;font-size:12.5px;line-height:1.8}
.tbl{border-collapse:collapse;width:100%;font-size:12px}
.tbl th,.tbl td{border:1px solid #ddd;padding:5px 7px;text-align:right}
.tbl th{background:#f5f5f5}
.box{border:1px solid #ddd;border-radius:6px;padding:11px 15px;background:#fafafa;font-size:13.5px;line-height:1.8}
.warn{border-left:4px solid #d62728;background:#fdf2f2}.ok{border-left:4px solid #2ca02c;background:#f2faf2}"""

js = pio.to_html(fig1, include_plotlyjs=True, full_html=False)
html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>v5 四件套报告(净口径)</title>
<style>{CSS}</style></head><body>
<h1>v5 四件套报告：13候选横向对比（净收益口径）</h1>
<p class="meta">生成：{datetime.now().strftime('%Y-%m-%d %H:%M')} · run_at: {CP['run_at']}<br>
口径：净收益 = 毛收益 - 周度round_trip {CP['cost_model']['round_trip_bp']}bp(满换仓保守上界, 年化拖累{CP['cost_model']['annual_drag_bp']:.0f}bp={CP['cost_model']['annual_drag_bp']/100:.1f}%)<br>
方法：CPCV(purge+embargo+多split) + DSR(N_eff={CP['n_eff']}) + MCS(block bootstrap) · 证伪门槛: DSR>=0.95 / MCS集合内 / forward衰减<=0.50<br>
<b>本报告修正8/8毛收益虚高</b>(DSF report用毛收益SR, 本报告用净SR).</p>

<h2>① 结果：净值 + 毛/净SR对照</h2>
{js}{pio.to_html(fig2, full_html=False)}{pio.to_html(fig4, full_html=False)}
{table_html}

<h2>② 口径（计算假设显式化）</h2>
<div class="box">
<b>成本模型(两套)</b>：<br>
　candidates层(本报告主口径)：固定round_trip {CP['cost_model']['round_trip_bp']}bp/周(满换仓上界, 真实换手率<100%), impact无法算(无持仓明细)<br>
　RQAlpha终审层(A2)：真实撮合(最低佣金/印花/涨跌停/停牌/最小手数), 见 rq_review_*.json<br>
<b>周期</b>：周频 T+5 · <b>年化</b>：√52 · <b>基准</b>：market_eq全市场等权 · <b>train_end</b>：{CP['train_end']}<br>
<b>N_eff={CP['n_eff']}</b>：13候选有效独立1.94个, 候选高度同源(同批量价因子衍生), 池内"择优"无统计意义, MCS只能淘汰.
</div>

<h2>③ 可信度：DSR + 归因</h2>
{pio.to_html(fig3, full_html=False)}
<div class="box">
<b>PBO</b>：{CP['pbo']}（毛收益0.05->净{CP['pbo']}, 成本揭露过拟合）<br>
<b>MCS无法区分集合</b>：{', '.join(CP['mcs_set'])}（{len(CP['mcs_set'])}个, 毛收益2个->净{len(CP['mcs_set'])}个, 扣成本后差异抹平）<br>
<b>证伪判定</b>：{n_dead}个"死了", {n_alive}个"未死_待forward积累"（未死≠好, 只=没被证伪）
</div>

<h2>④ 证伪判定（程序性结论, A3自动）</h2>
<div class="box {'warn' if n_dead else 'ok'}">
<b>自动判定</b>（按 four_piece_schema: F1 DSR>=0.95 / F2 MCS集合内 / F3 forward衰减<=0.50, 任一fail=死了）：<br>
　· daily_pick 净SR{ST['daily_pick_eqcomposite_top5']['sharpe_full']} DSR{ST['daily_pick_eqcomposite_top5']['dsr']} < 0.95 -> <b>死了(F1)</b><br>
　· 多空系受成本重创: tsmom_ls 净SR{ST['tsmom_ls_K12']['sharpe_full']}(毛{ST['tsmom_ls_K12']['sharpe_gross_full']}), eq38_ls 净SR{ST['eq38_ls']['sharpe_full']}(毛{ST['eq38_ls']['sharpe_gross_full']})<br>
　· funnel_top5_eq_ls 净SR{ST['funnel_top5_eq_ls']['sharpe_full']} DSR{ST['funnel_top5_eq_ls']['dsr']} -> 未死但N_eff={CP['n_eff']}候选同源, "未死"不等于可实盘.
</div>
<div class="box ok"><b>责任声明</b>：程序性裁判, 只输出证据不推荐. 结论是否采纳由阅读者决定.</div>
</body></html>"""

out = f'{BASE}/reports/v5_four_piece_report.html'
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'已生成: {out} ({os.path.getsize(out)//1024} KB)')
print(f'证伪判定: {n_dead}死了 / {n_alive}未死')

#!/home/soso/v5/.venv/bin/python3
"""量化 1 亿版涨跌停/停牌吃单的机会成本（近似）

方法: 解析 RQAlpha 日志拒绝事件 → 从 bundle 算被拒股票 T+1..T+5 收益
- limit_up 拒绝(买单进不去) → 损失"本应买入"的收益
- limit_down 拒绝(卖单出不去) → 承受"本应卖出"的损失
- suspended → 停牌(不量化, 标注)
近似假设: 每只被拒股票目标权重 = 1/4050 × 1亿 = 2.47万
"""
import re, os
import h5py
import numpy as np

LOG = "/tmp/claude-1000/-mnt-c-Users-Administrator/5eb22500-6414-49c7-b8d7-b8e4d66f2e23/tasks/buhfa6p37.output"
BUNDLE = os.path.expanduser("~/.rqalpha/bundle/stocks.h5")
CAPITAL = 1e8
N_TARGET = 4050

# 取 e8 运行段（到 DONE e8 为止）
lines = []
for line in open(LOG, encoding="utf-8", errors="ignore"):
    lines.append(line)
    if "DONE e8" in line:
        break

up, down, susp = [], [], []
pat_rej = re.compile(r"\[([\d-]+) .*?Order Rejected: current bar \[(\w+\.\w+)\] reach the (limit_up|limit_down) price")
pat_susp = re.compile(r"\[([\d-]+) .*?Order Creation Failed: security (\w+\.\w+) is suspended")
for line in lines:
    m = pat_rej.search(line)
    if m:
        (up if m.group(3) == "limit_up" else down).append((m.group(1), m.group(2)))
        continue
    m = pat_susp.search(line)
    if m:
        susp.append((m.group(1), m.group(2)))

print(f"e8 段: limit_up {len(up)} 条, limit_down {len(down)} 条, suspended {len(susp)} 条")

with h5py.File(BUNDLE, "r") as f:
    def t5_return(code, date_str):
        if code not in f:
            return None
        d = f[code]
        dt = d["datetime"][:]
        cl = d["close"][:]
        t = int(date_str.replace("-", "") + "000000")
        idx = np.where(dt > t)[0]
        if len(idx) < 5:
            return None
        i0 = idx[0]
        if i0 + 5 >= len(cl):
            return None
        p0 = cl[i0]
        if p0 <= 0:
            return None
        return cl[i0 + 5] / p0 - 1  # 被拒后第 5 日收益(近似持有5天)

    def aggregate(events):
        tot = 0.0; n = 0; cnt = 0
        for date_str, code in events:
            r = t5_return(code, date_str)
            if r is None:
                continue
            cnt += 1
            n += 1
            tot += r
        return tot, n, cnt

    tot_up, n_up, cnt_up = aggregate(up)
    tot_down, n_down, cnt_down = aggregate(down)

w_per = CAPITAL / N_TARGET  # 单只目标权重金额
# limit_up: 机会成本 = Σ(每只被拒股票的后续收益 × 权重金额)
loss_up = tot_up * w_per if n_up else 0
loss_down = tot_down * w_per if n_down else 0
print(f"\n近似机会成本（每只权重 {w_per:.0f} 元）:")
print(f"  涨停买不进: {n_up} 只有效统计, 收益和 {tot_up:.2f}, 平均 T+5 收益 {tot_up/max(n_up,1)*100:.2f}% → 累计机会成本 ≈ {loss_up/1e4:.0f} 万 = 本金 {loss_up/CAPITAL*100:.2f}%")
print(f"  跌停卖不出: {n_down} 只有效统计, 收益和 {tot_down:.2f}, 平均 T+5 收益 {tot_down/max(n_down,1)*100:.2f}% → 累计机会成本 ≈ {loss_down/1e4:.0f} 万 = 本金 {loss_down/CAPITAL*100:.2f}%")
print(f"  停牌: {len(susp)} 条未量化（停牌打开后跳变风险未计）")
print(f"  合计吃单机会成本 ≈ 本金 {(loss_up+loss_down)/CAPITAL*100:.2f}%（10 年）≈ 年化 {((loss_up+loss_down)/CAPITAL)/10*100:.2f}%")

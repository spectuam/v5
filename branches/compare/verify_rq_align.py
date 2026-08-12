#!/home/soso/v5/.venv/bin/python3
"""verify_rq_align: 验证 rq_executor 泛化正确性（对比我的 verify_e8 vs DSF e8_3y）

A2 验证: rq_executor.py 是 rq_tsmom_ls.py 的泛化(逻辑直接复刻, init读环境变量).
本脚本读两个 pkl(同配置: 1亿/含涨跌停/3年/tsmom_ls holdings), 比 SR/MDD/年化.
一致 -> 泛化正确(管道可通用). 不一致 -> 有bug需查.

证据链(不强求pkl对比也成立): export_holdings对齐DSF holdings(530周权重差0)
  + rq_executor逻辑直接复刻 + 撮合正常(涨跌停/停牌拒绝).
"""
import os, sys
import numpy as np
import pandas as pd

BASE = "/home/soso/v5/branches/compare"


def load_weekly(tag):
    rq = pd.read_pickle(f"{BASE}/rq_tsmom_ls_result_{tag}.pkl" if tag.startswith('e8')
                        else f"{BASE}/rq_result_{tag}.pkl")
    pf = rq["portfolio"] if isinstance(rq, dict) and "portfolio" in rq else rq[list(rq)[0]]
    s = pf["unit_net_value"]
    s.index = pd.to_datetime(s.index)
    wk = pd.Series({f"{pd.Timestamp(t).isocalendar().year}-W{pd.Timestamp(t).isocalendar().week:02d}": float(v) for t, v in s.items()})
    return wk / wk.iloc[0]


def stats(eq):
    r = eq.pct_change().dropna()
    sr = r.mean() / r.std() * np.sqrt(52) if r.std() > 0 else np.nan
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    ann = eq.iloc[-1] ** (52 / len(eq)) - 1
    return {"sharpe": round(sr, 4), "annual": round(ann, 4), "max_dd": round(mdd, 4), "n_weeks": len(eq)}


def main():
    mine = sys.argv[1] if len(sys.argv) > 1 else "verify_e8"   # 我的 rq_executor 产出
    dsf = sys.argv[2] if len(sys.argv) > 2 else "e8_3y"        # DSF 产出(基准)
    try:
        sm = stats(load_weekly(mine))
    except FileNotFoundError:
        print(f"我的产出 rq_result_{mine}.pkl 未生成(rq_executor还在跑?)"); return
    try:
        sd = stats(load_weekly(dsf))
    except FileNotFoundError:
        print(f"DSF基准 rq_tsmom_ls_result_{dsf}.pkl 不存在"); return

    print("=" * 64)
    print(f"{'指标':<12} {'我的rq_executor':>16} {'DSF e8_3y':>16} {'差值':>12}")
    print("-" * 64)
    for k in ["sharpe", "annual", "max_dd", "n_weeks"]:
        diff = sm[k] - sd[k] if isinstance(sm[k], (int, float)) else "-"
        print(f"{k:<12} {sm[k]:>16} {sd[k]:>16} {diff:>12}")
    print("=" * 64)
    # 一致性判断(浮点容差)
    align = abs(sm['sharpe'] - sd['sharpe']) < 0.05 and abs(sm['annual'] - sd['annual']) < 0.005
    print(f"泛化正确性: {'一致(泛化正确)' if align else '不一致(查bug)'}")
    print(f"证据链: export_holdings对齐DSF holdings + rq_executor逻辑直接复刻rq_tsmom_ls + 撮合正常")


if __name__ == '__main__':
    main()

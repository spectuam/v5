#!/home/soso/v5/.venv/bin/python3
"""rq_terminal_review: RQAlpha 终审对比 + 归因（通用，A2）

输入: --pkl <rq_result_tag.pkl> --strategy <name> [--nolimit-pkl <path>] [--out <path>]
输出: 三口径对比(毛收益/净收益candidates固定成本/RQAlpha真实撮合) + 归因拆解(费用/涨跌停/停牌)

泛化自 DSF rq_compare.py + rq_attribution_3y.py(tsmom_ls专用, 硬编码 long_leg.json).
双层管道终审出口: 自写快筛(毛/净) -> RQAlpha终审(本脚本读pkl) -> 四件套(A3 schema).
归因需含涨跌停(nolimit)pkl做对照; 单pkl只做三口径对比不拆解.
"""
import json, os, argparse
import numpy as np
import pandas as pd

COMPARE = os.path.expanduser('~/v5/branches/compare/compare_pool_result.json')


def week_key(ts):
    iso = pd.Timestamp(ts).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def load_rq_weekly(pkl_path):
    """RQAlpha pkl -> 周净值 Series(起点=1)"""
    rq = pd.read_pickle(pkl_path)
    df = rq["portfolio"] if isinstance(rq, dict) and "portfolio" in rq else (rq[list(rq)[0]] if isinstance(rq, dict) else rq)
    col = None
    for c in ["unit_net_value", "net_value", "total_value"]:
        if c in df.columns:
            col = c; break
    if col is None:
        raise ValueError(f"RQAlpha 列无净值: {list(df.columns)}")
    s = df[col]
    s.index = pd.to_datetime(s.index)
    wk = pd.Series({week_key(ts): float(v) for ts, v in s.items()})
    return wk / wk.iloc[0]


def stats(eq, freq=52):
    r = eq.pct_change().dropna()
    sr = r.mean() / r.std() * np.sqrt(freq) if r.std() > 0 else np.nan
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    ann = eq.iloc[-1] ** (freq / len(eq)) - 1 if len(eq) else np.nan
    return {"sharpe": round(float(sr), 3), "annual": round(float(ann), 4),
            "max_dd": round(float(mdd), 4), "n_weeks": int(len(eq))}


def load_trades(pkl_path):
    rq = pd.read_pickle(pkl_path)
    return rq.get("trades") if isinstance(rq, dict) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pkl', required=True, help='RQAlpha 结果 pkl(含涨跌停)')
    ap.add_argument('--strategy', required=True, help='策略名(对齐 compare_pool_result)')
    ap.add_argument('--nolimit-pkl', help='无涨跌停 pkl(归因拆解用, 可选)')
    ap.add_argument('--out', help='输出 JSON 路径')
    args = ap.parse_args()

    # RQAlpha 真实口径
    rq_w = load_rq_weekly(args.pkl)
    rq_st = stats(rq_w)
    trades = load_trades(args.pkl)

    # compare_pool 毛/净口径
    cmp = json.load(open(COMPARE))
    strat = cmp.get('strategies', {}).get(args.strategy, {})
    gross_sr = strat.get('sharpe_gross_full')
    net_sr = strat.get('sharpe_full')
    dsr = strat.get('dsr')

    print("=" * 72)
    print(f"RQAlpha 终审对比: {args.strategy}")
    print("-" * 72)
    print(f"{'口径':<26} {'年化':>8} {'夏普':>7} {'MDD':>8}  说明")
    print("-" * 72)
    print(f"{'毛收益(自写快筛)':<26} {'-':>8} {gross_sr:>7} {'-':>8}  无成本无涨跌停")
    print(f"{'净收益(candidates固定10.2bp)':<26} {'-':>8} {net_sr:>7} {'-':>8}  满换仓保守上界")
    print(f"{'RQAlpha真实撮合':<26} {rq_st['annual']*100:>7.1f}% {rq_st['sharpe']:>7} {rq_st['max_dd']*100:>7.1f}%  佣金/印花/涨跌停/停牌/最小手数")
    print("=" * 72)

    out = {
        "strategy": args.strategy,
        "caliber": {"layer": "RQAlpha终审", "cost_model": "真实撮合(最低佣金/印花/涨跌停/停牌/最小手数)"},
        "comparison": {
            "gross_sharpe": gross_sr, "net_candidates_sharpe": net_sr, "rqalpha_sharpe": rq_st['sharpe'],
            "rqalpha_annual": rq_st['annual'], "rqalpha_max_dd": rq_st['max_dd'],
            "dsr": dsr,
            "cost_drag_gross_to_rq": round(gross_sr - rq_st['sharpe'], 3) if gross_sr else None,
        },
    }

    # 归因拆解(需 nolimit pkl)
    if args.nolimit_pkl and trades is not None:
        rq_nl = load_rq_weekly(args.nolimit_pkl)
        nl_st = stats(rq_nl)
        # 费用(trades实测, 年化占比)
        fee_total = float(trades['tax'].sum() + trades['commission'].sum())
        notional = float((trades['last_price'] * trades['last_quantity']).sum())
        fee_pct = fee_total / notional if notional else 0
        # 涨跌停贡献 = 含限制 - 无限制
        limit_contrib = rq_st['annual'] - nl_st['annual']
        print(f"\n归因拆解(年化):")
        print(f"  费率(实测): {fee_pct*100:.3f}% (费{fee_total/1e4:.0f}万/成交{notional/1e8:.1f}亿)")
        print(f"  涨跌停限制贡献: {limit_contrib*100:+.2f}pp (含限制{rq_st['annual']*100:.1f}% - 无限制{nl_st['annual']*100:.1f}%)")
        print(f"  停牌+其余: (无限制 - 理想 - 费用, 理想=毛收益口径)")
        out['attribution'] = {
            "fee_pct_of_notional": round(fee_pct, 5),
            "limit_up_down_contrib_annual": round(limit_contrib, 4),
            "rq_nolimit": nl_st,
        }

    out_path = args.out or os.path.expanduser(f'~/v5/branches/compare/rq_review_{args.strategy}.json')
    json.dump(out, open(out_path, 'w'), indent=2, ensure_ascii=False, default=float)
    print(f"\nwritten: {out_path}")


if __name__ == '__main__':
    main()

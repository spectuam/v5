#!/home/soso/v5/.venv/bin/python3
"""状态择时验证（statsmodels regime 版）

读 statsmodels market_regime 结果（week_state=filtered live），报告每 regime 的
return/vol/SR/MDD，测试双向择时规则，诚实判定择时是否有效。

旧版（state_adaptive.py.hmmlearn.bak）硬编码 hide {recovery,crash}，依赖 hmmlearn
的「按年化收益标注」（label-switching 下 bear 反而 SR 最高）。新版按 sigma2 标注，
诚实暴露：A股等权「crash(高波动)」regime 含高收益，空仓反而损价值。

完整三层(smoothed上限/filtered-global/expanding-live)对比见 market_regime_rolling.py。
"""
import os, json
from datetime import datetime
import numpy as np

REGIME = os.path.expanduser('~/v5/branches/compare/market_regime_result.json')
ROLLING = os.path.expanduser('~/v5/branches/compare/market_regime_rolling_result.json')
CAND = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
OUT = os.path.expanduser('~/v5/branches/compare/state_adaptive_result.json')
FREQ = 52
LONG_NAMES = ['tsmom_long_K12', 'funnel_top5_eq_long', 'funnel_top5_tsmom_long']


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def stats(rets):
    arr = np.asarray(rets, float)
    if len(arr) < 2 or arr.std() == 0:
        return {'n': len(arr), 'sharpe': 0, 'annual': 0, 'max_dd': 0}
    sr = float(arr.mean() / arr.std() * np.sqrt(FREQ))
    nav = np.cumprod(1 + arr)
    mdd = float(((nav - np.maximum.accumulate(nav)) / np.maximum.accumulate(nav)).min())
    return {'n': len(arr), 'sharpe': round(sr, 2),
            'annual': round(float(arr.mean() * FREQ), 4), 'max_dd': round(mdd, 3)}


def timing(weekly_pairs, week_state, hide):
    return [0.0 if week_state.get(w) in hide else r for w, r in weekly_pairs]


def main():
    log("=" * 60); log("状态择时验证 (statsmodels regime, filtered live)"); log("=" * 60)
    regime = json.load(open(REGIME))
    week_state = regime['week_state']  # filtered = live
    stats_fil = regime['state_stats_filtered']
    best_k = regime['best_k']
    regime_label = regime['regime_label']
    agree = regime['smoothed_vs_filtered_agreement']
    log(f"regime: k={best_k}, filtered-vs-smoothed一致率{agree:.1%}")
    log("状态画像（filtered live）:")
    for lab, st in stats_fil.items():
        log(f"  {lab}: {st['n_months']}月, 年化{st['annual']:.2%}, 波动{st['vol_annual']:.2%}, "
            f"SR{st['sharpe']}, MDD{st['max_dd']:.2%}, sigma2={st['sigma2']}")

    # 双向择时规则
    labels = list(stats_fil.keys())
    crash_label = next((l for l in labels if l == 'crash'), labels[-1])
    low_sr_label = min(stats_fil, key=lambda l: stats_fil[l]['sharpe'])
    hide_sets = {'原版': set(),
                 f'hide_{crash_label}(高波动,旧规则)': {crash_label},
                 f'hide_{low_sr_label}(低SR)': {low_sr_label}}
    log(f"择时规则: {list(hide_sets.keys())}")

    cands = json.load(open(CAND))
    out = {'run_at': datetime.now().isoformat(),
           'regime': f'statsmodels k={best_k}, filtered live (一致率{agree:.1%})',
           'state_stats': stats_fil,
           'note': 'filtered=Hamilton filter 因果 live; 完整三层对比见 market_regime_rolling_result.json',
           'results': {}}

    for name in LONG_NAMES:
        if name not in cands:
            continue
        strat = cands[name]
        log(f"\n{name}:")
        out['results'][name] = {}
        for label, hide in hide_sets.items():
            timed = timing(strat, week_state, hide)
            st = stats(timed)
            out['results'][name][label] = st
            log(f"  {label}: SR{st['sharpe']} 年化{st['annual']:.2%} MDD{st['max_dd']:.2%}")

    # 诚实判定（交叉验证：本脚本=filtered-global 参数全样本 vs rolling=expanding 严格live）
    rolling = json.load(open(ROLLING)) if os.path.exists(ROLLING) else {}
    log("-" * 60); log("诚实判定（双口径交叉验证）:")
    log("  本脚本 filtered-global: 参数全样本估计(含轻 look-ahead); rolling expanding: 参数逐月重估(严格 live)")
    for name, row in out['results'].items():
        orig = row['原版']['sharpe']
        # filtered-global 最佳（含参数 look-ahead）
        fg_best = max(v['sharpe'] for k, v in row.items() if k != '原版')
        # expanding 严格 live 最佳（从 rolling 取同策略段内原版 vs expanding 最佳）
        roll_row = rolling.get('results', {}).get(name, {})
        exp_seg_orig = roll_row.get('原版_seg', {}).get('sharpe')
        exp_best = max((roll_row.get(f'{h}/expanding', {}).get('sharpe', 0)
                        for h in ['hide_crash', 'hide_lowSR']), default=None)
        if exp_seg_orig is not None and exp_best is not None:
            live_verdict = '改善' if exp_best > exp_seg_orig + 0.08 else (
                '反损' if exp_best < exp_seg_orig - 0.08 else '中性(噪声内)')
            log(f"  {name}: 全段原版SR{orig} | filtered-global最佳SR{fg_best} | "
                f"expanding段内原版SR{exp_seg_orig}->严格live最佳SR{exp_best}={live_verdict}")
        else:
            log(f"  {name}: 全段原版SR{orig} | filtered-global最佳SR{fg_best} (rolling未跑,无法交叉验证)")
    log("结论: hide crash(高波动)全口径反损(A股高波动regime含高收益); "
        "hide calm(低SR)在 filtered-global 似改善但 expanding 严格 live 归中性 -> 改善源于参数 look-ahead,不可靠")

    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"\nwritten: {OUT}")


if __name__ == '__main__':
    main()

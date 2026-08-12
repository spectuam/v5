#!/home/soso/v5/.venv/bin/python3
"""v5 每日候选证伪状态报告（A4 改造：不推选股，推程序性裁判报告）

定位修正(8/8晚): v5 = 程序性裁判系统 + 四件套. 证伪主义, 不越权推荐.
原 daily_pick_v5.py 推 Top5 选股 = 价值性输出, 与新定位冲突.
A4 改造: 不推选股, 推"候选证伪状态报告"(表现+证据+证伪判定).

读:
  - compare_pool_result.json (13候选净口径+毛对照+DSR+MCS, A1)
  - rq_review_daily_pick_eqcomposite_top5.json (daily_pick RQAlpha真实口径, A2)
按 four_piece_schema(A3) 证伪门槛判定了/未死, 飞书推送.

v5 不再背生产责任(不推Top5). 用不用由老板定.
选股逻辑(strategy_factory.produce_picks)保留配置化, 本脚本不调用.
"""
import sys, os, json
from datetime import datetime, date

COMPARE = os.path.expanduser('~/v5/branches/compare/compare_pool_result.json')
RQ_REVIEW = os.path.expanduser('~/v5/branches/compare/rq_review_daily_pick_eqcomposite_top5.json')
REPORT_DIR = os.path.expanduser('~/ading/data/reports')
LOG_FILE = os.path.expanduser('~/ading/logs/daily_pick_v5.log')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# A3 证伪门槛
F1_DSR = 0.95
F3_DECAY = 0.50


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def falsify(name, s, mcs_set):
    """A3 证伪判定: F1 DSR + F2 MCS + F3 forward衰减(任一fail=死了)"""
    reasons = []
    dsr = s.get('dsr', 0)
    if dsr < F1_DSR:
        reasons.append(f"DSR{dsr:.3f}<0.95")
    if name not in mcs_set:
        reasons.append("被MCS排除")
    tr = s.get('sharpe_train', 0)
    if tr > 0.1:  # IS有正表现才算衰减, 否则无从衰减
        decay = max(0, 1 - s.get('sharpe_oos', 0) / tr)
        if decay > F3_DECAY:
            reasons.append(f"forward衰减{decay:.2f}>0.50")
    return ('未死' if not reasons else '死了'), (', '.join(reasons) if reasons else '全过')


def build_report():
    cp = json.load(open(COMPARE))
    st = cp['strategies']
    mcs_set = cp.get('mcs_set', [])
    cm = cp['cost_model']

    # daily_pick RQAlpha真实口径(A2)
    rq_line = ""
    if os.path.exists(RQ_REVIEW):
        rq = json.load(open(RQ_REVIEW))
        cmp = rq.get('comparison', {})
        rq_line = (f"\ndaily_pick 真实口径(RQAlpha): SR{cmp.get('rqalpha_sharpe','-')} "
                   f"年化{cmp.get('rqalpha_annual','-'):.1%} -> 亏损证伪")

    today_str = date.today().strftime("%Y-%m-%d")
    lines = [
        f"v5 候选证伪状态报告 - {today_str}",
        f"定位: 程序性裁判(证伪主义, 不推荐) | 净口径(扣周度{cm['round_trip_bp']}bp满换仓上界)",
        "=" * 44,
        f"{'候选':<22}{'净SR':>6}{'毛SR':>6}{'DSR':>7}{'MCS':>5}{'判定':>6}",
        "-" * 44,
    ]
    n_dead = n_alive = 0
    for name, s in st.items():
        verdict, _ = falsify(name, s, mcs_set)
        if verdict == '死了':
            n_dead += 1
        else:
            n_alive += 1
        short = name[:20]
        lines.append(f"{short:<22}{s['sharpe_full']:>6.2f}{s['sharpe_gross_full']:>6.2f}"
                     f"{s['dsr']:>7.3f}{'是' if name in mcs_set else '否':>5}{verdict:>6}")
    lines.append("=" * 44)
    lines.append(f"池: {n_dead}死了 / {n_alive}未死 | n_eff={cp['n_eff']}(同源) | PBO={cp['pbo']}(成本揭露过拟合)")
    if rq_line:
        lines.append(rq_line)
    lines.append("-" * 44)
    lines.append("责任声明: 只输出证据不推荐. 结论是否采纳由阅读者决定.")
    return "\n".join(lines), n_dead, n_alive


def send_feishu(text):
    print(text)
    try:
        sys.path.insert(0, os.path.expanduser("~"))
        from feishu import send_text, MONITOR_CHAT_ID
        send_text(text, chat_id=MONITOR_CHAT_ID)
        log("Feishu sent")
    except Exception as e:
        log(f"Feishu failed: {e}")
    path = os.path.join(REPORT_DIR, f"candidate_falsify_{date.today()}.md")
    with open(path, "w") as f:
        f.write(text)
    log(f"saved: {path}")


def main():
    log("=" * 50)
    log("v5 候选证伪状态报告 (A4: 不推选股, 推程序性裁判报告)")
    if not os.path.exists(COMPARE):
        log(f"FATAL: {COMPARE} 不存在, 先跑 compare_pool.py"); return
    text, n_dead, n_alive = build_report()
    send_feishu(text)
    log(f"Done: {n_dead}死了/{n_alive}未死")


if __name__ == '__main__':
    main()

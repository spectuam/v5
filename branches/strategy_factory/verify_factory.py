#!/home/soso/v5/.venv/bin/python3
"""验证 strategy_factory.rank_and_pick == daily_pick_v5.rank_and_pick（行为零变更）
用 daily_pick 原版 build_panel + load_factors 喂两个 rank_and_pick，diff picks。"""
import sys, os, json
from datetime import date
sys.path.insert(0, '/home/soso/v5')
sys.path.insert(0, '/home/soso/v5/branches/strategy_factory')
import daily_pick_v5 as dp
import strategy_factory as sf

cfg = sf.load_config(os.path.expanduser('~/v5/branches/strategy_factory/strategy_config.json'))
today_str = date.today().strftime("%Y-%m-%d")
print(f"date={today_str}")

# 原版 panel + factor_ids（同一份，喂两边）
panel = dp.build_panel(today_str)
factor_ids = dp.load_factors()
print(f"factors={len(factor_ids)}")

picks_A = dp.rank_and_pick(panel, factor_ids)
picks_B = sf.rank_and_pick(panel, factor_ids, cfg)

print("\n=== daily_pick 原版 ===")
print(json.dumps(picks_A, ensure_ascii=False))
print("\n=== factory ===")
print(json.dumps(picks_B, ensure_ascii=False))
print("\n" + ("MATCH ✓ 行为零变更" if picks_A == picks_B else "DIFF ✗ 需排查"))

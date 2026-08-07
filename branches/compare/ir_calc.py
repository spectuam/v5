#!/home/soso/v5/.venv/bin/python3
"""路A 强度+稳定：IC均值 + IR(IC均值/IC标准差)

IR = IC均值 / IC标准差 (Grinold主动管理IR≈IC·√BR, 这里直接算)
和IC排序互补: 同IC均值, IR惩罚波动大的不稳定因子。
"""
import sqlite3, os, json
from datetime import datetime
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/compare/ir_result.json')


def main():
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    out = {}
    for fid in orth:
        rows = db.execute("SELECT T20_IC FROM factor_ic_daily WHERE factor_id=? AND T20_IC IS NOT NULL", (fid,)).fetchall()
        if not rows:
            continue
        ics = np.array([r[0] for r in rows])
        mean = float(np.mean(ics))
        std = float(np.std(ics))
        ir = mean / std if std > 0 else 0
        out[fid] = {'ic_mean': round(mean, 4), 'ic_std': round(std, 4), 'ir': round(ir, 3)}
    db.close()
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)

    # IR排序
    ranked = sorted(out.items(), key=lambda x: -x[1]['ir'])
    print(f"路A IR: {len(out)}因子")
    print("top5 IR:")
    for f, v in ranked[:5]:
        print(f"  {f}: IC={v['ic_mean']:+.4f} std={v['ic_std']:.4f} IR={v['ir']:+.3f}")
    print(f"written: {OUT}")


if __name__ == '__main__':
    main()

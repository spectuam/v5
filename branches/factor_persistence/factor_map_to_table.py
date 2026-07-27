#!/home/soso/v5/.venv/bin/python3
"""factor_map JSON -> 扁平 CSV + sqlite 表
每行: granularity, period, factor, return, percentile, rank
方便筛选/排序/前3前5/横向纵向分析
"""
import json, csv, sqlite3, os

SRC = os.path.expanduser('~/v5/branches/factor_persistence/factor_map_result.json')
CSV_OUT = os.path.expanduser('~/v5/branches/factor_persistence/factor_map.csv')
DB_OUT = os.path.expanduser('~/ading/db/tdx_stock_data.db')

d = json.load(open(SRC))

rows = []
for gran, periods in d.items():
    for period, pdata in periods.items():
        all_factors = pdata.get('all', {})
        # 按 pct 排序算 rank
        sorted_facs = sorted(all_factors.items(), key=lambda x: -x[1]['pct'])
        for rank, (fname, fdata) in enumerate(sorted_facs, 1):
            rows.append({
                'granularity': gran,
                'period': period,
                'factor': fname,
                'return': fdata['ret'],
                'percentile': fdata['pct'],
                'rank': rank,
                'is_best': 1 if fname == pdata.get('best') else 0,
            })

# CSV
with open(CSV_OUT, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['granularity', 'period', 'factor', 'return', 'percentile', 'rank', 'is_best'])
    w.writeheader()
    w.writerows(rows)
print(f"CSV: {CSV_OUT} ({len(rows)} rows)")

# sqlite
db = sqlite3.connect(DB_OUT)
db.execute("DROP TABLE IF EXISTS factor_map")
db.execute("""CREATE TABLE factor_map (
    granularity TEXT, period TEXT, factor TEXT,
    return REAL, percentile REAL, rank INTEGER, is_best INTEGER
)""")
db.executemany("INSERT INTO factor_map VALUES (?,?,?,?,?,?,?)",
               [(r['granularity'], r['period'], r['factor'], r['return'], r['percentile'], r['rank'], r['is_best']) for r in rows])
db.commit()
db.close()
print(f"sqlite: factor_map 表 ({len(rows)} rows)")

# 示例查询
db = sqlite3.connect(DB_OUT)
print("\n=== 示例: month 每切片前3 ===")
for period in ['2025-10', '2026-04', '2026-05']:
    print(f"\n{period}:")
    for r in db.execute("SELECT factor, return, percentile FROM factor_map WHERE granularity='month' AND period=? ORDER BY rank LIMIT 3", (period,)):
        print(f"  {r[0]}: ret={r[1]:+.4f} pct={r[2]:.2f}")
db.close()

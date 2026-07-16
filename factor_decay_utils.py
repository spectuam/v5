#!/home/soso/v5/.venv/bin/python3
"""v5 因子衰减测试 — 工具函数
- 面板构建 (daily_kline → panel)
- IC 计算 (Spearman rank, 适配自 vibe-trading compute_ic_series)
- 随机对照组 (shuffle within rows)
- 相关矩阵 + 贪婪正交去重
- 指数衰减拟合 + 半衰期
"""
import sqlite3, os, sys, time
import numpy as np
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional

DB = os.path.expanduser("~/ading/db/stock_data.db")
TDX_DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
_MIN_VALID_PER_DATE = 30  # 每天至少多少有效对才算
_MIN_VALID_DAYS = 20       # 至少多少天有效 IC 才保留

# ─────────────────────────────────────────────
# 1. 面板构建
# ─────────────────────────────────────────────

def build_daily_panel(lookback_days: int = 250, db_path: str = None) -> Dict[str, pd.DataFrame]:
    """从 daily_kline (后复权) 构建 panel, 返回 {close/open/high/low/volume}

    Args:
        lookback_days: 回看天数
        db_path: 数据库路径, None=默认baostock, 'tdx'=通达信
    """
    if db_path is None:
        db_path = DB
    elif db_path == 'tdx':
        db_path = TDX_DB
    db = sqlite3.connect(db_path)
    min_date = db.execute(
        "SELECT date(MAX(date), ? || ' days') FROM daily_kline",
        (f'-{lookback_days}',)
    ).fetchone()[0]

    # 检查是否有 stock_info 表 (baostock有, tdx没有)
    has_stock_info = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='stock_info'"
    ).fetchone()[0] > 0

    if has_stock_info:
        df = pd.read_sql("""
            SELECT d.code, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount
            FROM daily_kline d
            JOIN stock_info s ON d.code = s.symbol
            WHERE d.date >= ? AND d.close > 0 AND d.open > 0
              AND s.class = 'stock'
              AND s.name NOT LIKE '%%ST%%'
              AND d.code NOT LIKE 'bj.%%'
            ORDER BY d.code, d.date
        """, db, params=(min_date,))
    else:
        df = pd.read_sql("""
            SELECT code, date, open, high, low, close, volume, amount
            FROM daily_kline
            WHERE date >= ? AND close > 0 AND open > 0
              AND code NOT LIKE 'sz.399%%'
            ORDER BY code, date
        """, db, params=(min_date,))
    db.close()

    df['date'] = pd.to_datetime(df['date'])
    # VWAP = 成交额 / 成交量
    df['vwap'] = df['amount'] / df['volume']
    df['vwap'] = df['vwap'].replace([np.inf, -np.inf], np.nan)

    panel = {}
    for field in ['open', 'high', 'low', 'close', 'volume', 'vwap', 'amount']:
        wide = df.pivot(index='date', columns='code', values=field)
        wide = wide.sort_index().astype('float32')
        panel[field] = wide

    return panel


def panel_date_range(panel: Dict[str, pd.DataFrame]) -> Tuple[str, str]:
    """返回 panel 的日期范围"""
    dates = panel['close'].index
    return str(dates[0].date()), str(dates[-1].date())


# ─────────────────────────────────────────────
# 2. 前向收益
# ─────────────────────────────────────────────

def compute_forward_returns(panel: Dict[str, pd.DataFrame],
                             horizons: List[int] = (1, 3, 5, 10, 20)
                             ) -> Dict[int, pd.DataFrame]:
    """计算多周期前向收益。

    Returns:
        {horizon: DataFrame(date×code)} 例如 {1: T+1收益, 3: T+3收益, ...}
    每个 cell = (close_{t+H} / close_t) - 1
    """
    close = panel['close']
    fwd = {}
    for H in horizons:
        fwd[H] = close.shift(-H) / close - 1.0
    return fwd


# ─────────────────────────────────────────────
# 3. IC 计算 (适配自 vibe-trading)
# ─────────────────────────────────────────────

def compute_ic_series(factor_df: pd.DataFrame,
                      return_df: pd.DataFrame) -> pd.Series:
    """计算每日 Spearman rank IC。

    适配自 vibe-trading src/factors/factor_analysis_core.py

    Args:
        factor_df: 因子值 DataFrame (date × code)
        return_df: 前向收益 DataFrame (date × code)

    Returns:
        pd.Series indexed by date, values = daily Spearman rank IC
    """
    # 对齐日期和股票
    common_dates = factor_df.index.intersection(return_df.index)
    common_codes = factor_df.columns.intersection(return_df.columns)

    if len(common_dates) == 0 or len(common_codes) == 0:
        return pd.Series(dtype=float)

    fac = factor_df.loc[common_dates, common_codes]
    ret = return_df.loc[common_dates, common_codes]

    # 构建配对 mask
    mask = fac.notna() & ret.notna()

    # 每日 rank
    fac_rank = fac.rank(axis=1, pct=False)
    ret_rank = ret.rank(axis=1, pct=False)

    # 行间 Pearson = Spearman
    ic = fac_rank.corrwith(ret_rank, axis=1)

    # 只保留每天 >= _MIN_VALID_PER_DATE 有效对的行
    valid_counts = mask.sum(axis=1)
    ic = ic[valid_counts >= _MIN_VALID_PER_DATE]

    return ic.dropna()


def compute_ic_summary(ic_series: pd.Series) -> dict:
    """从 IC 序列计算汇总指标"""
    n = len(ic_series)
    if n < _MIN_VALID_DAYS:
        return {'IC_mean': np.nan, 'IC_std': np.nan, 'IR': np.nan,
                'IC>0': np.nan, 'n_days': n}

    ic_mean = float(ic_series.mean())
    ic_std = float(ic_series.std())
    ir = ic_mean / ic_std if ic_std > 0 else 0.0
    ic_pos = float((ic_series > 0).mean())

    return {'IC_mean': round(ic_mean, 6), 'IC_std': round(ic_std, 6),
            'IR': round(ir, 4), 'IC>0': round(ic_pos, 4), 'n_days': n}


# ─────────────────────────────────────────────
# 4. 随机对照 (适配自 vibe-trading bench_runner_strict)
# ─────────────────────────────────────────────

def _shuffle_within_rows(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    """行内随机排列，NaN/Inf 固定在原位不动。

    适配自 vibe-trading bench_runner_strict._shuffle_within_rows()
    """
    rng = np.random.default_rng(seed)
    result = df.copy()
    for i in range(len(df)):
        row = result.iloc[i].values
        finite_mask = np.isfinite(row)
        if finite_mask.sum() < 2:
            continue
        shuffled = row[finite_mask]
        rng.shuffle(shuffled)
        result.iloc[i, finite_mask] = shuffled
    return result


def compute_random_ic_series(factor_df: pd.DataFrame,
                             return_df: pd.DataFrame,
                             n_seeds: int = 5,
                             base_seed: int = 42) -> pd.Series:
    """计算随机对照 IC 序列。

    对每个 seed 创建一个打乱后的因子，算 IC，然后取均值。
    """
    ic_list = []
    for s in range(n_seeds):
        shuffled = _shuffle_within_rows(factor_df, seed=base_seed + s)
        ic = compute_ic_series(shuffled, return_df)
        ic_list.append(ic)

    if not ic_list:
        return pd.Series(dtype=float)

    # inner join across all seeds
    result = ic_list[0].copy()
    for ic_s in ic_list[1:]:
        common_idx = result.index.intersection(ic_s.index)
        result = result.loc[common_idx] + ic_s.loc[common_idx]

    return result / len(ic_list)


def alpha_series_paired(signal_ic: pd.Series,
                        random_ic: pd.Series) -> pd.Series:
    """信号 IC - 随机 IC"""
    common = signal_ic.index.intersection(random_ic.index)
    return signal_ic.loc[common] - random_ic.loc[common]


def t_stat(series: pd.Series) -> float:
    """单样本 t 统计量"""
    n = len(series)
    if n < 2:
        return 0.0
    std = series.std()
    if std == 0 or np.isnan(std):
        return 0.0
    return float(series.mean() / (std / np.sqrt(n)))


# ─────────────────────────────────────────────
# 5. 相关矩阵 + 贪婪正交去重
# ─────────────────────────────────────────────

def compute_correlation_matrix(factor_values: Dict[str, pd.Series],
                               min_common: int = 100) -> pd.DataFrame:
    """计算因子间相关矩阵

    Args:
        factor_values: {factor_id: stacked_series} (所有日期的值 stack 成一个长 Series)

    Returns:
        相关矩阵 DataFrame, index/columns = factor_ids
    """
    fids = list(factor_values.keys())
    n = len(fids)
    corr_mat = pd.DataFrame(np.eye(n), index=fids, columns=fids)

    for i in range(n):
        for j in range(i + 1, n):
            si = factor_values[fids[i]]
            sj = factor_values[fids[j]]
            common = si.index.intersection(sj.index)
            if len(common) < min_common:
                c = 0.0
            else:
                c = si.loc[common].corr(sj.loc[common])
                c = c if not np.isnan(c) else 0.0
            corr_mat.iloc[i, j] = c
            corr_mat.iloc[j, i] = c

    return corr_mat


def greedy_orthogonalize(ic_scores: Dict[str, float],
                         corr_mat: pd.DataFrame,
                         corr_threshold: float = 0.7) -> List[str]:
    """贪婪正交去重：按 IC 从高到低，corr > threshold 的踢掉

    Args:
        ic_scores: {factor_id: IC_mean}
        corr_mat: 相关矩阵

    Returns:
        正交因子 ID 列表
    """
    sorted_fids = sorted(ic_scores.keys(), key=lambda x: ic_scores[x], reverse=True)
    clustered = set()
    orthogonal = []

    for fid in sorted_fids:
        if fid in clustered:
            continue
        orthogonal.append(fid)
        clustered.add(fid)

        idx = corr_mat.index.get_loc(fid)
        for j in range(len(corr_mat)):
            if corr_mat.iloc[idx, j] > corr_threshold:
                clustered.add(corr_mat.index[j])

    return orthogonal


# ─────────────────────────────────────────────
# 6. 指数衰减拟合 + 半衰期
# ─────────────────────────────────────────────

def fit_decay_curve(horizons: List[int],
                    ic_values: List[float]) -> Tuple[Optional[float], float, dict]:
    """拟合指数衰减 IC(τ) = IC₀ × e^(-λτ)

    Args:
        horizons: 周期列表 [1, 3, 5, 10, 20]
        ic_values: 对应的 IC 均值

    Returns:
        (half_life_days, r_squared, fit_detail)
        half_life_days = None 表示拟合失败
    """
    from scipy.optimize import curve_fit

    x = np.array(horizons, dtype=float)
    y = np.array(ic_values, dtype=float)

    # 去掉 NaN
    valid = ~np.isnan(y)
    if valid.sum() < 3:
        return None, 0.0, {'error': 'too few valid IC points'}

    x_v, y_v = x[valid], y[valid]

    # IC₀ 必须为正
    if y_v[0] <= 0:
        return None, 0.0, {'error': 'IC₀ <= 0'}

    def exp_decay(t, ic0, lam):
        return ic0 * np.exp(-lam * t)

    try:
        popt, pcov = curve_fit(exp_decay, x_v, y_v,
                               p0=[y_v[0], 0.1],
                               bounds=([0, 0], [1.0, 1.0]),
                               maxfev=1000)
        ic0, lam = popt[0], max(popt[1], 1e-6)

        # R²
        y_pred = exp_decay(x_v, ic0, lam)
        ss_res = np.sum((y_v - y_pred) ** 2)
        ss_tot = np.sum((y_v - y_v.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        half_life = np.log(2) / lam if lam > 0 else None

        return (float(half_life) if half_life and half_life < 365 else 365.0,
                round(r2, 4),
                {'ic0': round(ic0, 6), 'lambda': round(lam, 6), 'r2': round(r2, 4)})

    except Exception as e:
        return None, 0.0, {'error': str(e)}


def categorize_factor(ic_mean: float, ic_positive: float,
                      half_life: Optional[float],
                      alpha_t: float, r2: float,
                      thresholds: dict = None,
                      ic_by_horizon: dict = None) -> dict:
    """因子分类

    规则（按优先顺序）:
      1. IC<ic_min → eliminated (dead)
      2. alpha_t<alpha_t_min → eliminated (noise) — 过不了随机对照
      3. half_life<2天 → eliminated (too_short) — 散户抓不住
      4. R²<r2_min:
           a. IC 在长周期(T+20)持平或更高 → persistent (长半衰期20天)
             依据: 指数衰减拟合不了"不衰减"的因子，但实际预测力不降，
                   应标记为持续性因子而非淘汰
           b. 否则 → degraded (默认3天)
      5. 正常衰减 → 按半衰期分 short/medium/long
    """
    if thresholds is None:
        thresholds = {'ic_min': 0.03, 'alpha_t_min': 2.0,
                      'half_life_min': 2.0, 'r2_min': 0.3}

    th = thresholds

    # 门槛 1: IC 太弱
    if ic_mean < th['ic_min']:
        return {'category': 'eliminated', 'status': 'dead',
                'reason': f'IC_mean={ic_mean:.4f} < {th["ic_min"]}'}

    # 门槛 2: 随机对照
    if alpha_t < th['alpha_t_min']:
        return {'category': 'eliminated', 'status': 'noise',
                'reason': f'alpha_t={alpha_t:.1f} < {th["alpha_t_min"]}'}

    # 门槛 3: 半衰期太短
    if half_life is not None and half_life < th['half_life_min']:
        return {'category': 'eliminated', 'status': 'too_short',
                'reason': f'half_life={half_life:.1f}d < {th["half_life_min"]}d'}

    # 衰减不收敛
    if r2 < th['r2_min']:
        # 检查是否"不衰减"而非"拟合失败"
        # 依据: 如果T+20的IC ≥ T+1的IC，说明因子预测力不随时间衰减
        # 指数衰减模型对此无效(R²低)，但因子本身值得保留
        if ic_by_horizon:
            ic_t1 = ic_by_horizon.get('T+1')
            ic_t20 = ic_by_horizon.get('T+20')
            if ic_t1 is not None and ic_t20 is not None and ic_t20 >= ic_t1 * 0.9:
                return {'category': 'persistent', 'status': 'confirmed',
                        'half_life': 20.0,
                        'reason': f'T+20 IC(={ic_t20:.4f}) ≥ T+1(={ic_t1:.4f})×0.9 — 不衰减',
                        'r2': r2}

        return {'category': 'degraded', 'status': 'unstable',
                'reason': f'R²={r2:.2f} < {th["r2_min"]}, unstable decay, using default half-life=3d',
                'half_life': 3.0}

    # 正常分类
    if half_life is None:
        return {'category': 'degraded', 'status': 'no_fit', 'half_life': 3.0}

    if half_life <= 5:
        hl_cat = 'short'; freq = 'daily'
    elif half_life <= 15:
        hl_cat = 'medium'; freq = 'weekly'
    else:
        hl_cat = 'long'; freq = 'biweekly'

    return {'category': hl_cat, 'status': 'confirmed',
            'half_life': round(half_life, 1), 'recommended_freq': freq,
            'r2': r2}

#!/home/soso/v5/.venv/bin/python3
"""路E 经济先验标注：38因子经济逻辑类型 + 先验强度

Harvey 2017/Arnott-Harvey-Markowitz: 经济合理性是第一道筛。
对现有38公开量价因子(都是alpha101/gtja191/qlib158已知因子,非纯挖掘),路E主要归类+标强度,
全部过硬筛(economic_pass=True),真正剔除价值在阶段5扩充纯挖掘因子。

经济类型(trend/momentum/volume/reversal/volatility/formula):
- trend: 均值/趋势(ma/vma) - 动量(反应不足) 文献强
- momentum: 动量(alpha_016等) - 行为偏差 文献强
- volume: 量能(vsumn/cntn) - 流动性/注意力 中
- reversal: 极值反转(min) - 过度反应 中
- volatility: 波动类 - 低波异常(风险溢价) 中
- formula: 公式组合(alpha101/gtja191编号) - 技术组合 弱-中

先验强度(strong/medium/weak): 影响funnel打分,强先验加分。
"""
import os, json

JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/compare/economics_prior.json')


def classify(fid):
    """基于因子id模式标注经济类型+先验强度"""
    # qlib158 系列(名字明确)
    if fid.startswith('qlib158/'):
        name = fid.split('/')[1]
        if name.startswith('ma') or name.startswith('vma'):
            return 'trend', 'strong'      # 均值/趋势=动量(反应不足)
        if name.startswith('min') or name.startswith('max'):
            return 'reversal', 'medium'   # 极值=反转(过度反应)
        if name.startswith('vsumn') or name.startswith('cntn'):
            return 'volume', 'medium'     # 量能=流动性/注意力
        return 'qlib_other', 'medium'
    # 文献强阳的动量因子(GK/EL因子动量+之前v5分析)
    if fid in ('alpha101/alpha_016', 'gtja191/alpha_016'):
        return 'momentum', 'strong'       # 因子动量强阳(文献+diagnose)
    if fid in ('alpha101/alpha_044', 'alpha101/alpha_015'):
        return 'momentum', 'medium'       # 之前分析有alpha但d1_collapse
    # alpha101/gtja191 公式因子(需查公式细化,先标formula)
    if fid.startswith('alpha101/') or fid.startswith('gtja191/'):
        return 'formula', 'weak'          # 技术组合,经济解释弱
    return 'unknown', 'weak'


def main():
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    out = {}
    for fid in orth:
        etype, strength = classify(fid)
        out[fid] = {
            'economic_type': etype,
            'prior_strength': strength,
            'economic_pass': True,  # 38公开因子都过(非纯挖掘);阶段5扩充时纯挖掘标False
            'note': f'{etype}类,先验{strength}'
        }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)

    # 汇总
    from collections import Counter
    types = Counter(v['economic_type'] for v in out.values())
    strengths = Counter(v['prior_strength'] for v in out.values())
    print(f"路E标注: {len(out)}因子, 全部过硬筛(economic_pass=True)")
    print(f"经济类型分布: {dict(types)}")
    print(f"先验强度分布: {dict(strengths)}")
    print(f"written: {OUT}")
    print("注: alpha101/gtja191编号因子标formula/weak,需老板查公式细化经济含义")


if __name__ == '__main__':
    main()

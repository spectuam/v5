export const meta = {
    name: 'v5-five-lines',
    description: 'v5 五线实验: 因子选择(Line A) + ML(Line E) → 方案对比(Line B/C/D) → 综合评审(Line F)',
    phases: [
        { title: 'Phase 1: Line A + E', detail: '因子选择(Train 2006-2015) + ML训练(Train)' },
        { title: 'Phase 2: Line B + C + D', detail: '周期稳定性 + BayesianRidge + 全量等权 (Valid 2016-2020)' },
        { title: 'Phase 3: Line F', detail: '综合评审 + Test最终评估(2021-2026)' },
    ],
}

const VENV = '/home/soso/v5/.venv/bin/python3'
const V5 = '/home/soso/v5'

// ═══════════════════════════════════════════
// Phase 1: Line A + Line E 并行
// ═══════════════════════════════════════════
phase('Phase 1: Line A + E')

const [resultA, resultE] = await Promise.all([
    // Line A: 因子选择 (Train only)
    agent(
        `Run factor decay scan on Train period (2006-2015) only.

Command:
${VENV} ${V5}/factor_decay_scan.py --tdx --date-end 2015-12-31

This should take about 1 hour. Wait for it to complete.
If it fails, report the error clearly.`,
        { label: 'Line A: factor selection' }
    ),

    // Line E: ML pipeline
    agent(
        `Run the Qlib ML pipeline for Line E.

Command:
${VENV} ${V5}/line_e_qlib_ml.py

This builds Qlib binary from TDX data and trains LightGBM. About 30 min.
If Qlib import fails or other errors occur, report them but don't block the workflow.`,
        { label: 'Line E: Qlib ML' }
    ),
])

log('Line A output: ' + (resultA || 'completed'))
log('Line E output: ' + (resultE || 'completed'))

// ═══════════════════════════════════════════
// Phase 2: Line B + C + D 并行
// ═══════════════════════════════════════════
phase('Phase 2: Line B + C + D')

const [resultB, resultC, resultD] = await Promise.all([
    agent(
        `Run Line B — cycle stability backtest.

Command:
${VENV} ${V5}/line_bcd_backtest.py --mode cycle

Report the stability score and per-cycle WR.`,
        { label: 'Line B: cycle stability' }
    ),

    agent(
        `Run Line C — BayesianRidge walk-forward.

Command:
${VENV} ${V5}/line_bcd_backtest.py --mode ridge

Report Ridge WR vs Equal WR and whether it breaks 53%.`,
        { label: 'Line C: BayesianRidge' }
    ),

    agent(
        `Run Line D — equal weight comparison.

Command:
${VENV} ${V5}/line_bcd_backtest.py --mode equal

Report best config (Top3/Top5/All) and its WR.`,
        { label: 'Line D: equal weight' }
    ),
])

log('Line B: ' + (resultB || 'completed'))
log('Line C: ' + (resultC || 'completed'))
log('Line D: ' + (resultD || 'completed'))

// ═══════════════════════════════════════════
// Phase 3: Line F 综合评审 + 最终评估
// ═══════════════════════════════════════════
phase('Phase 3: Line F')

const resultF = await agent(
    `Run Line F — synthesis and final Test evaluation.

Command:
${VENV} ${V5}/line_f_synthesis.py

This will:
1. Read all results from Lines B/C/D/E
2. Compare and select the best approach
3. Run the final test on Test period (2021-2026)
4. Output the final verdict

Report the final WR, return percentile, and verdict clearly.`,
    { label: 'Line F: synthesis' }
)

log('Line F: ' + (resultF || 'completed'))
log('ALL FIVE LINES COMPLETE.')

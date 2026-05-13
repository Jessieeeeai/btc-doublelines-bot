"""
两线缠绕容差测试: 5 档对比
T1 = 0% (当前严格)
T2 = 0.05% (刚好抓到上面那个 $28 闪失的形态)
T3 = 0.10% (中等放宽)
T4 = 0.25% (中偏松)
T5 = 0.50% (相对松)
T6 = 1.00% (放飞)
基础都是 F6 (regime_mode='optimal' + 突破入场 + 2%缓冲 + 2R)
"""
from backtest import VariantConfig


def _f6(name, tol=0.0):
    return VariantConfig(
        name=name,
        body_ratio=0.5,
        entanglement_tolerance=tol,
        r_multiple=2.0,
        sl_buffer_pct=0.02,
        entry_mode="breakout_confirm",
        entry_wait_bars=3,
        regime_mode="optimal",
        regime_adx_high=25,
        regime_ema_dist_trend=0.02,
    )


VARIANTS = [
    _f6("T1_tol_0.00pct",  0.0),
    _f6("T2_tol_0.05pct",  0.0005),
    _f6("T3_tol_0.10pct",  0.001),
    _f6("T4_tol_0.25pct",  0.0025),
    _f6("T5_tol_0.50pct",  0.005),
    _f6("T6_tol_1.00pct",  0.01),
]

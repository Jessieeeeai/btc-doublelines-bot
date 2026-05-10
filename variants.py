"""
F-系列: 基于"跳过强趋势期 + M2 顺势"的新发现, 测试不同阈值
  F1: M2 control (旧冠军)
  F2: optimal regime (默认阈值)
  F3-F5: optimal 不同 ADX 阈值
  F6-F8: optimal 不同 EMA 偏离阈值
  F9: skip trend only (其他不过滤)
  F10: E6 baseline 对照
"""
from backtest import VariantConfig


def _b2(name, **kw):
    defaults = dict(body_ratio=0.5, r_multiple=2.0, sl_buffer_pct=0.02,
                    entry_mode="breakout_confirm", entry_wait_bars=3)
    defaults.update(kw)
    return VariantConfig(name=name, **defaults)


VARIANTS = [
    _b2("F1_M2_control",          ema_filter_period=200),

    _b2("F2_optimal_default",     regime_mode="optimal",
        regime_adx_high=25, regime_ema_dist_trend=0.03),

    _b2("F3_optimal_ADX20",       regime_mode="optimal",
        regime_adx_high=20, regime_ema_dist_trend=0.03),

    _b2("F4_optimal_ADX30",       regime_mode="optimal",
        regime_adx_high=30, regime_ema_dist_trend=0.03),

    _b2("F5_optimal_ADX35",       regime_mode="optimal",
        regime_adx_high=35, regime_ema_dist_trend=0.03),

    _b2("F6_optimal_dist2pct",    regime_mode="optimal",
        regime_adx_high=25, regime_ema_dist_trend=0.02),

    _b2("F7_optimal_dist5pct",    regime_mode="optimal",
        regime_adx_high=25, regime_ema_dist_trend=0.05),

    _b2("F8_optimal_ADX22dist2",  regime_mode="optimal",
        regime_adx_high=22, regime_ema_dist_trend=0.02),

    # 只跳过趋势但不加 M2 顺势 (作为对比)
    _b2("F9_skip_trend_only",     regime_mode="switch",
        regime_adx_high=25, regime_adx_low=0,  # chop 永远不触发
        regime_ema_dist_trend=0.03, regime_ema_dist_chop=999,
        regime_skip_transition=False),

    # E6 control: regime no-skip (mixed M2+M9)
    _b2("F10_E6_mixed_control",   regime_mode="switch",
        regime_adx_high=25, regime_adx_low=20,
        regime_ema_dist_trend=0.03, regime_ema_dist_chop=0.015,
        regime_skip_transition=False),
]

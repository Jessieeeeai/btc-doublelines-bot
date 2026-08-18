"""
重叠K线颈线突破 — 信号检测器 (新策略, 与双线反战完全独立)

形态定义 (2026-08-17 与大漂亮确认):
- 两根相邻的K线 (中间不隔其他K线), 实体 (不含影线) 有交集
- 重叠长度 L = 两个实体交集的高度
- 颈线: 交集上沿 = 上颈线 (overlap_hi), 交集下沿 = 下颈线 (overlap_lo)
- 重叠判定: 交集高度 > ratio × 参照实体高度
  参照实体 4 种模式 (ref_mode):
    "longer"  较长那根实体
    "shorter" 较短那根实体
    "first"   第一根实体
    "second"  第二根实体
  ratio 默认 0.5, 可调

口径声明 (阶段2.5 固定, 不做多口径扫描):
- 实体高度 = |close - open|; 两根实体高度都必须 > 0 (光头doji不参与)
- 交集为闭区间比较, 交集高度必须严格 > 阈值
- 每对相邻K线独立评估, 允许连续K线产生连续信号 (是否成交由回测层串行决定)
"""
from typing import List, Dict, Any

REF_MODES = ("longer", "shorter", "first", "second")


def _body(bar: Dict[str, float]):
    lo = min(bar["open"], bar["close"])
    hi = max(bar["open"], bar["close"])
    return lo, hi, hi - lo


def detect_overlap_signals(bars: List[Dict[str, Any]],
                           ref_mode: str = "longer",
                           ratio: float = 0.5) -> List[Dict[str, Any]]:
    """
    扫描K线序列, 返回所有重叠形态。
    信号是"中性"的: 不带方向, 方向由后续价格先破哪条颈线决定 (回测层处理)。
    index = 第二根K线的下标 (形态在这根收盘时确认)。
    """
    if ref_mode not in REF_MODES:
        raise ValueError(f"ref_mode 必须是 {REF_MODES} 之一, 收到: {ref_mode}")

    signals = []
    for i in range(1, len(bars)):
        b1, b2 = bars[i - 1], bars[i]
        lo1, hi1, h1 = _body(b1)
        lo2, hi2, h2 = _body(b2)
        if h1 <= 0 or h2 <= 0:
            continue

        ov_lo = max(lo1, lo2)
        ov_hi = min(hi1, hi2)
        L = ov_hi - ov_lo
        if L <= 0:
            continue

        if ref_mode == "longer":
            ref_h = max(h1, h2)
        elif ref_mode == "shorter":
            ref_h = min(h1, h2)
        elif ref_mode == "first":
            ref_h = h1
        else:  # second
            ref_h = h2

        if L <= ratio * ref_h:
            continue

        signals.append({
            "index": i,
            "date": b2["date"],
            "overlap_lo": ov_lo,
            "overlap_hi": ov_hi,
            "L": L,
            "body1_h": h1,
            "body2_h": h2,
            "ref_h": ref_h,
        })
    return signals


if __name__ == "__main__":
    # 自检: 两根实体大部分重叠
    test = [
        {"date": "t0", "open": 100.0, "high": 106, "low": 99,  "close": 105.0},
        {"date": "t1", "open": 101.0, "high": 107, "low": 100, "close": 106.0},  # 实体101-106, 交集101-105=4, longer=5
    ]
    for m in REF_MODES:
        s = detect_overlap_signals(test, m, 0.5)
        print(m, len(s), s[0] if s else "")

#!/usr/bin/env python3
"""修子 feed 在订阅平台水位线处的跳号。

背景 (2026-09-15): 平台按每个子 feed 独立连续消费, 已处理到 event_id=100 (旧的全局编号时代)。
拆分成"每文件独立连续编号"后, 新事件从各文件末尾接着编, 结果 B 文件 100 之后是 102, C 是 103,
平台卡在"缺少 101"。A 文件恰好有 101 所以没事。

做法: 对水位线之后的事件整体下移, 让第一条紧接水位线 (W+1), 之后保持连续; next_event_id 重算。
水位线之前的历史跳号平台已经消费过, 不动。

用法:  python3 research/fix_feed_gap.py B:100 C:100
"""
import json
import sys


def fix(path, watermark):
    d = json.load(open(path))
    ev = d.get("events", [])
    tail = [e for e in ev if e["event_id"] > watermark]
    if not tail:
        print(f"{path}: 水位 {watermark} 之后没有事件, 跳过")
        return False
    first = min(e["event_id"] for e in tail)
    shift = first - (watermark + 1)
    if shift <= 0:
        print(f"{path}: 水位 {watermark} 之后第一条是 {first}, 已连续, 不用改")
        return False
    tail.sort(key=lambda e: e["event_id"])
    # 尾部重编: 紧接水位线, 严格连续 (顺带修掉尾部内部可能的跳号)
    nid = watermark + 1
    for e in tail:
        e.setdefault("old_event_id", e["event_id"])
        e["event_id"] = nid
        nid += 1
    ev.sort(key=lambda e: e["event_id"])
    d["events"] = ev
    d["next_event_id"] = ev[-1]["event_id"] + 1
    with open(path, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    ids = [e["event_id"] for e in ev]
    after = [i for i in ids if i > watermark]
    print(f"{path}: 尾部 {len(tail)} 条下移 {shift} -> {after[0]}..{after[-1]} 连续={after == list(range(after[0], after[-1] + 1))}, next={d['next_event_id']}")
    return True


if __name__ == "__main__":
    args = sys.argv[1:] or ["B:100", "C:100"]
    for a in args:
        code, w = a.split(":")
        fix(f"signals_feed_{code}.json", int(w))

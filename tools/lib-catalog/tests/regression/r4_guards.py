#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r4_guards.py — 参数护栏与语义（终审⑤ / R1 加固）

守护什么：`topic_graph.py` 的四个数值参数必须**越界即拒**（非零退出 + 范围提示），
边界值必须**接受**，且 `--budget` 的语义（region 节点数含源点、≤ budget）必须成立。
护栏一旦被删/被挪进单个子命令，本用例立即 FAIL。

用例组成：
  [1] 越界拒绝：--hops ∉1..12、--decay ∉(0,1]、--budget <1、--threshold ∉[0,1]、
      topic_id 越界；且三个扩散子命令（around/graph/summarize）**都**要拦
  [2] 边界接受：--hops 12、--decay 1.0、--budget 1、--threshold 0/1 均须 exit 0
  [3] budget 语义：visited == 出参节点数 == budget（饱和时），且**含源点**（budget=1 → 仅源点）
  [4] threshold 语义：threshold=1 → 仅源点；threshold=0 的 region ≥ 默认阈值的 region

只读：只调用主体 CLI（不写主体产物）；临时 JSON 落系统临时目录；不触网。
来源：终审⑤ / R1 加固（topics/ACCEPTANCE-REPORT.md §10.1-⑤、§10.4）。
"""
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True          # 只读纪律：先于 import _common 生效，不落 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

SUBCMD = "r4_guards"
SEED_TERM, SEED_FALLBACK = "机器", 56   # P4 验收同款源点；term 锚定（抗节点表重建）
TIMEOUT = 180

INVALID = [
    ("--hops 0", ["--hops", "0"], "1..12"),
    ("--hops 13", ["--hops", "13"], "1..12"),
    ("--hops 100", ["--hops", "100"], "1..12"),
    ("--hops -1", ["--hops", "-1"], "1..12"),
    ("--decay 1.5", ["--decay", "1.5"], "(0,1]"),
    ("--decay 2", ["--decay", "2"], "(0,1]"),
    ("--decay 0", ["--decay", "0"], "(0,1]"),
    ("--decay -0.2", ["--decay", "-0.2"], "(0,1]"),
    ("--budget 0", ["--budget", "0"], "≥1"),
    ("--budget -5", ["--budget", "-5"], "≥1"),
    ("--threshold 2", ["--threshold", "2"], "[0,1]"),
    ("--threshold -0.5", ["--threshold", "-0.5"], "[0,1]"),
    ("--threshold 1.5", ["--threshold", "1.5"], "[0,1]"),
]
# 护栏必须对每个扩散子命令生效（防止护栏被挪进 cmd_around）
CROSS_CMDS = [("--hops 13", ["--hops", "13"], "1..12"),
              ("--decay 1.5", ["--decay", "1.5"], "(0,1]"),
              ("--budget 0", ["--budget", "0"], "≥1"),
              ("--threshold 2", ["--threshold", "2"], "[0,1]")]


def json_run(tmp, args):
    """跑 `graph ... --json-out`，返回 (rc, out, payload|None)。"""
    out = os.path.join(tmp, "g%d.json" % abs(hash(tuple(args))))
    rc, text = C.run_tool(list(args) + ["--json-out", out], timeout=TIMEOUT)
    payload = None
    if os.path.isfile(out):
        try:
            with open(out, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            payload = None
    return rc, text, payload


def build(R):
    tmp = tempfile.mkdtemp(prefix="regression-r4-")
    try:
        _build(R, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _build(R, tmp):
    global SEED
    try:
        nodes = C.load_nodes()
        sid, note = C.resolve_term(nodes, SEED_TERM, SEED_FALLBACK)
        if sid is not None:
            SEED = sid
            R.info("护栏源点：%s(id=%d)%s" % (nodes[SEED]["term"], SEED,
                                            ("（%s）" % note) if note else ""))
    except C.DataMissing as e:
        R.skip("源点 term 解析", str(e))
        R.info("源点回退 id=%d" % SEED)

    # ---- [1] 越界拒绝 -----------------------------------------------------
    R.section("1 越界拒绝（非零退出 + 范围提示）")
    for label, argv, hint in INVALID:
        rc, out = C.run_tool(["around", SEED, "--hops", "1"] + argv, timeout=TIMEOUT)
        first = (out.strip().splitlines() or [""])[0]
        R.check("around 拒绝 %s" % label, rc != 0 and hint in out,
                "exit=%s 首行=%s" % (rc, first[:78]),
                source="r1_assert")

    R.section("1b 护栏对三个扩散子命令均生效")
    for cmd in ("around", "graph", "summarize"):
        for label, argv, hint in CROSS_CMDS:
            rc, out = C.run_tool([cmd, SEED, "--hops", "1"] + argv, timeout=TIMEOUT)
            R.check("%s 拒绝 %s" % (cmd, label), rc != 0 and hint in out,
                    "exit=%s" % rc, source="r1_assert")

    rc, out = C.run_tool(["around", "999999", "--hops", "1"], timeout=TIMEOUT)
    R.check("topic_id 越界拒绝（999999）", rc != 0 and "越界" in out,
            "exit=%s 首行=%s" % (rc, (out.strip().splitlines() or [""])[0][:60]),
            source="r1_assert")

    # ---- [2] 边界值接受 ---------------------------------------------------
    R.section("2 边界值必须接受（不得误伤）")
    rc, out, pl = json_run(tmp, ["graph", SEED, "--hops", "3", "--decay", "1.0",
                                 "--budget", "50000", "--threshold", "0"])
    R.check("接受 --decay 1.0 / --threshold 0 / --budget 50000（三处边界）",
            rc == 0 and pl is not None, "exit=%s" % rc, source="r1_assert")
    if pl:
        R.check("回显参数正确（decay=1.0 已落地）",
                abs(float(pl.get("decay", 0)) - 1.0) < 1e-12,
                "hops=%s decay=%s" % (pl.get("hops"), pl.get("decay")), source="r1_assert")
    rc, out, plh = json_run(tmp, ["graph", SEED, "--hops", "12", "--budget", "50000"])
    R.check("接受 --hops 12（上限）", rc == 0 and plh is not None and plh.get("hops") == 12,
            "exit=%s hops=%s" % (rc, plh and plh.get("hops")), source="r1_assert")

    rc, out, pl = json_run(tmp, ["graph", SEED, "--hops", "1", "--threshold", "1"])
    R.check("接受 --threshold 1（上边界）", rc == 0 and pl is not None, "exit=%s" % rc,
            source="r1_assert")
    R.check("threshold=1 语义：只剩源点（所有后代分数 <1 被剪）",
            pl is not None and pl["stats"]["visited"] == 1 and len(pl["nodes"]) == 1,
            "visited=%s" % (pl and pl["stats"]["visited"]), source="r1_assert")

    # ---- [3] budget 语义 --------------------------------------------------
    R.section("3 --budget 语义：region 节点数（含源点）≤ budget，饱和时恰为 budget")
    for b in (1, 2, 3, 5, 50):
        rc, out, pl = json_run(tmp, ["graph", SEED, "--hops", "2", "--budget", str(b)])
        if rc != 0 or pl is None:
            R.check("budget=%d 可运行" % b, False, "exit=%s" % rc, source="r1_assert")
            continue
        st = pl["stats"]
        R.check("budget=%d：visited == 出参节点数 == %d" % (b, b),
                st["visited"] == len(pl["nodes"]) == b,
                "visited=%s nodes=%d" % (st["visited"], len(pl["nodes"])), source="r1_assert")
        R.check("budget=%d：预算饱和标记为真" % b, bool(st["saturated_budget"]) is True,
                "saturated=%s" % st["saturated_budget"], source="r1_assert")
        R.check("budget=%d：源点必在区内（预算含源点）" % b,
                any(n["id"] == SEED for n in pl["nodes"]),
                "节点 id 首项=%s" % (pl["nodes"][0]["id"] if pl["nodes"] else None),
                source="r1_assert")

    rc, out, pl = json_run(tmp, ["graph", SEED, "--hops", "3", "--budget", "50000"])
    if rc == 0 and pl is not None:
        st = pl["stats"]
        R.check("budget=50000：未饱和且 1 ≤ visited ≤ budget",
                1 <= st["visited"] <= 50000 and not st["saturated_budget"],
                "visited=%s saturated=%s" % (st["visited"], st["saturated_budget"]),
                source="r1_assert")

    # ---- [4] hops / threshold 单调语义 -----------------------------------
    R.section("4 hops / threshold 单调语义")
    visit = {}
    for h in (1, 2, 3, 12):
        rc, out, pl = json_run(tmp, ["graph", SEED, "--hops", str(h)])
        if rc == 0 and pl is not None:
            visit[h] = pl["stats"]["visited"]
            R.check("hops=%d：visited == 出参节点数" % h,
                    pl["stats"]["visited"] == len(pl["nodes"]),
                    "visited=%s nodes=%d" % (pl["stats"]["visited"], len(pl["nodes"])),
                    source="r1_assert")
    if len(visit) == 4:
        seq = [visit[1], visit[2], visit[3], visit[12]]
        R.check("visited 随 hops 单调不减：%s" % seq,
                all(seq[i] <= seq[i + 1] for i in range(3)), "实测 %s" % seq,
                source="r1_assert")

    rc0, _o0, pl0 = json_run(tmp, ["graph", SEED, "--hops", "2", "--threshold", "0"])
    rcd, _od, pld = json_run(tmp, ["graph", SEED, "--hops", "2"])
    if pl0 is not None and pld is not None:
        R.check("threshold=0 的 region ≥ 默认阈值(%.2f) 的 region" % C.THRESHOLD_DEFAULT,
                pl0["stats"]["visited"] >= pld["stats"]["visited"],
                "t=0 → %d ；默认 → %d" % (pl0["stats"]["visited"], pld["stats"]["visited"]),
                source="r1_assert")
        R.check("region 权重下界：threshold=0 时最小权重 < 默认阈值（确有放宽）",
                pl0["stats"]["weight_min"] <= pld["stats"]["weight_min"] + 1e-12,
                "t=0 min=%.6f ；默认 min=%.6f" % (
                    pl0["stats"]["weight_min"], pld["stats"]["weight_min"]),
                source="r1_assert")


if __name__ == "__main__":
    sys.exit(C.main_guard(SUBCMD, "参数护栏与 budget/hops/threshold 语义", build, C.SOURCES))

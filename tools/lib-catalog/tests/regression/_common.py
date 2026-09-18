#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/regression/_common.py — 回归测试集公共设施（REGRESSION-SET）

定位：**只读**回归资产。本模块不修改主体代码与验收脚本，只做三件事：
  1) 路径解析与数据装载（nodes.json / edges.csr.npz / card_topics.jsonl / cards.jsonl）
  2) **口径镜像**：把 P2/P4 的权重公式与关联度公式在这里只定义一次，供 r1/r2 复用，
     避免「各用例各写一份公式」导致的回归漂移
  3) PASS / WARN / FAIL 报告器（WARN = 已知未修缺陷，标注「待 R2」，不判 FAIL）

纪律：
  * `sys.dont_write_bytecode = True` —— 不在主体目录落 __pycache__（对现有产物只读）
  * 不触网：本模块与全部用例只用本地文件；子进程调用一律显式 `TOPIC_LLM=off`
  * 任何用例崩溃都由 `main_guard()` 转成 FAIL，绝不静默通过
"""
import json
import math
import os
import subprocess
import sys
import traceback

sys.dont_write_bytecode = True  # 只读纪律：主体的 __pycache__ 不因本回归集变动

REG_DIR = os.path.dirname(os.path.abspath(__file__))            # tests/regression
ROOT_DIR = os.path.dirname(os.path.dirname(REG_DIR))            # lib-catalog（主体工具链）
PYLIBS = os.path.expanduser("~/go/pylibs")

# ---- 口径常量：镜像 topic_graph.py / topic_edges.py 的冻结值（不重复实现，只引用） ----
DECAY_DEFAULT = 0.86
THRESHOLD_DEFAULT = 0.05
BUDGET_DEFAULT = 50000
HOPS_MAX = 12
CAP_COUNT = 50          # 共现书数封顶
MAX_OUT = 20            # 每节点出度上限（top-20 截断）
SAME_CLUSTER_BONUS = 0.3

# ---- 终审/审计已确认的冻结反例常量 ----
# 定位：**基线参考值（R2-E 已升级到 R2 后数值）**，用于"基线漂移报告"与失败时的可读诊断。
#   * 硬断言只建立在「不变量 / 公式恒等 / 跨表一致」上（产物被合法重建后仍必须成立）
#   * 下列数据相关数字**不作为硬等值断言**：图被重建（如 R2 轮）时会自然漂移，
#     误判成回归会制造假红；漂移由 Reporter.baseline() 报 WARN 并提示复核后再更新本表。
#   * **R2-E 升级（2026-09-18）**：R2-A 重建词表（5,187→5,507 节点 / 99,268→105,414 边）后，
#     下列数值已按 R2 后实测刷新；R1 期数值一律保留为 `*_pre_r1` / `*_r1_*` 历史锚点（仅作诊断与有牙性对照）。
#   * 已修条目（D1/M2/F2）的断言已由 r6 的 warn_check 升级为 check() 硬断言，见 r6_known_defects.py。
FROZEN = {
    # 终审①：settlement → entanglement 共现权重（R2 后 **不变**：该对仍仅 1 本书共现）
    "ce1_pair": ("settlement", "entanglement"),
    "ce1_mms": "991000938579704181",
    "ce1_c": 1,
    "ce1_weight_fixed": 0.1762914344,     # log1p(1)/log1p(50)，float64
    "ce1_weight_stored": 0.1762914360,    # float32 落盘值
    "ce1_weight_pre_r1": 0.2794153094,    # R1 前错值（回归必须不再出现）
    # 终审②：经济学 邻域 assoc 主排序键（R1 前 economist 缺席 / economic 在列）
    #   R2-E 更新：leaves(economic) 0.0353 → **0.0316**（R2-A 重建词表使 freq 变化：共现 39→35）；
    #   enters(economist) 0.0578 不变。判别式 assoc(enters) > assoc(leaves) 在 R2 后仍成立。
    "ce2_seed": "经济学",
    "ce2_enters": "economist",
    "ce2_leaves": "economic",
    "ce2_assoc_enters": 0.0578,
    "ce2_assoc_leaves": 0.0316,
    "ce2_assoc_leaves_r1": 0.0353,        # R1 基线（历史锚点）
    # 终审③：扩散超跳内存反例（请求 12 跳：BUGGY=13 边 / FIXED=12 边；R2 未变）
    "ce3_buggy_maxpath": 13,
    "ce3_fixed_maxpath": 12,
    # R1 加固断言：卡数（R2 未变）
    "cards": 188512,
    # ---- D1 层级边（R1：登记 4,832 / 实存 4,823 / 缺 9 → R2-A 修复：登记 = 实存 / 缺 0）----
    "d1_registered_hier": 5151,           # R2 后（R1 基线 4832）
    "d1_present_in_artifact": 5151,       # R2 后（R1 基线 4823）
    "d1_missing": 0,                      # R2 后（R1 基线 9）
    "d1_missing_pairs": (),               # R2 后无缺失；R1 清单见 d1_r1_missing_pairs
    "d1_r1_missing_pairs": (              # 历史锚点：须在 pre-r2 产物上仍可独立复现（有牙性）
        ("global", "F8"), ("实验", "TP3"), ("方法", "F2"), ("时代", "F2"),
        ("computational", "TP3"), ("世纪", "I2"), ("principles", "TP3"),
        ("经典", "TP3"), ("仿真", "TP3"),
    ),
    "d1_pre_r2_missing": 9,               # 有牙性对照：pre-r2 产物独立重算仍须得 9
    "d1_registered_hier_r1": 4832,        # R1 基线（历史锚点）
    # ---- M2 大小写（R2-B 选定策略：**检索时等值归一 norm_key**，未统一小写存储）----
    "m2_victims": 349,                    # nodes.json 中仍为大写的 cls 码数（策略既定，非缺陷）
    "m2_retrieval_consistent": True,      # 契约：存名 / 归一名查询命中同一节点
    # ---- F2 ext_df 双计数（R1：207,596 事件 / 580 词 ratio>1 → R2-A：0 / 0）----
    "f2_double_count_events": 0,          # R2 后（R1 证据快照 207596）
    "f2_ratio_gt1_terms": 0,              # R2 后（R1 证据快照 580）
    "f2_containment_ratio_max": 1.0,      # R2 后（R1 前 2.0 —— 卡级比值 >1 不可能）
    "f2_flips": 129,                      # 被双计数误剔、R2 后回归词表的 A 源词数
    "f2_a_kept": 1647,                    # R2 后 source_a_kept（R1 前 1518）
    "f2_a_kept_in_nodes": 1486,           # = R1 前 1357 + 129（其余 161 为 F18 英文门，未修）
    "f2_a_dropped_embedded": 765,         # R2 后（R1 前 894）
    "f2_a_dropped_zero_freq": 429,        # R2 未变
    "f2_a_set_n": 2841,                   # A 源候选集（R2 未变）
    "f2_nodes": 5507,                     # R2 后节点数（R1 5187）
    "f2_pre_r1_evidence": {"double_count_events": 207596, "ratio_gt1_terms": 580,
                           "flips": 129, "a_kept": 1518, "a_dropped_embedded": 894,
                           "a_kept_in_nodes": 1357},
    # ---- R2-C 新增：边型数组（bit0=共现 / bit1=同簇加成 / bit2=层级）----
    "types_domain": (1, 3, 5, 7),
}

# 审计/终审来源引用（README 与用例输出共用，保证"每条断言都可溯源"）
SOURCES = {
    "ce1": "终审① / topics/ACCEPTANCE-REPORT.md §10.1-①、§10.2",
    "ce2": "终审② / topics/ACCEPTANCE-REPORT.md §10.1-②、§10.2",
    "ce3": "终审③ / topics/ACCEPTANCE-REPORT.md §10.1-③、§10.2",
    "r1_assert": "终审⑤ / topics/ACCEPTANCE-REPORT.md §10.4（新增验收断言）",
    "d1": "topics/audit/num/REPORT.md §4（D1）+ topics/audit/edgetype/PROPOSAL.md §1.5 "
          "+ topics/audit/verify-fix/REPORT.md",
    "m2": "topics/audit/graph/REPORT.md M2/F19",
    "m6": "topics/audit/graph/REPORT.md M6/F5",
    "f2": "topics/audit/p1/REPORT.md F2/F2b（+ audit/p1/evidence/ext_double_count.json）",
    "r2e": "R2-E 会话（全链复跑 + 基线升级）/ topics/audit/r2-verify/REPORT.md；"
           "R2-A 修复：topics/audit/p1/R2A-FIX-REPORT.md；R2-C：topics/audit/r2c/REPORT.md",
    "types": "R2-C 边型数组 / topics/audit/edgetype/PROPOSAL.md §4.1 + "
             "topics/p2-build-report.json#params.b5_edgetype_rule",
}


class DataMissing(Exception):
    """必需产物缺失 —— 由 main_guard 转成 FAIL 并给出可操作提示。"""


class ToolFailed(Exception):
    """主体工具调用失败（非护栏拒绝）。"""


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
def data_dir():
    return os.path.abspath(os.path.expanduser(
        os.environ.get("LIB_CATALOG_DATA") or "~/go/lib-catalog-data"))


def topics_dir():
    return os.path.join(data_dir(), "topics")


def ensure_import_paths():
    """把 pylibs / 主体目录 / 本目录放进 sys.path（与主体脚本同源 numpy 环境）。"""
    for p in (PYLIBS, ROOT_DIR, REG_DIR):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)


def rel(path):
    """把绝对路径折叠成便于阅读的相对路径（相对 ~/go 或 ~）。"""
    ap = os.path.abspath(path)
    home = os.path.expanduser("~")
    for base, tag in ((os.path.join(home, "go"), "~/go/"), (home, "~/")):
        if ap.startswith(base + os.sep):
            return tag + os.path.relpath(ap, base)
    return ap


def resolve_term(nodes, term, fallback_id=None):
    """按 term 解析节点 id（**抗重建**：节点表重建后 id 会漂移，term 相对稳定）。

    返回 (id, note)：term 命中 → (id, "")；未命中且给了 fallback_id → (fallback_id, 说明)；
    两者皆无 → (None, 说明)。
    """
    for x in nodes:
        if x["term"] == term:
            return int(x["id"]), ""
    if fallback_id is not None and 0 <= fallback_id < len(nodes):
        return int(fallback_id), "term '%s' 未命中，回退 id=%d（%s）" % (
            term, fallback_id, nodes[fallback_id]["term"])
    return None, "term '%s' 与 fallback 均不可用（产物已重建？）" % term


def require_files(*paths):
    miss = [p for p in paths if not os.path.isfile(p) or os.path.getsize(p) == 0]
    if miss:
        raise DataMissing("缺少产物：" + "、".join(rel(p) for p in miss) +
                          "（重建：python3 topic_build.py / topic_edges.py --data <data>）")


# ---------------------------------------------------------------------------
# 口径镜像（公式只此一份）
# ---------------------------------------------------------------------------
def w_cooccurrence(count, count_sc, cap=CAP_COUNT):
    """共现边权（镜像 topic_edges.py）：

        w = min(1, log1p(min(c,cap))/log1p(cap) + 0.3·log1p(cs)/log1p(cap))
        c  = 同卡（卡 top-5 kw ∪ {卡 cls2}）共现书数
        cs = 其中「卡簇标签 == cluster(u) == cluster(v)」的书数
    """
    l = math.log1p(cap)
    c = int(count)
    cs = int(count_sc)
    return min(1.0, math.log1p(min(c, cap)) / l + SAME_CLUSTER_BONUS * math.log1p(cs) / l)


def assoc(count, freq_u, freq_v):
    """top-20 截断主排序键（镜像 topic_edges.py）：assoc = c / sqrt(freq_u · freq_v)。"""
    return int(count) / math.sqrt(max(int(freq_u), 1) * max(int(freq_v), 1))


# ---------------------------------------------------------------------------
# 装载
# ---------------------------------------------------------------------------
def load_nodes(T=None):
    T = T or topics_dir()
    p = os.path.join(T, "nodes.json")
    require_files(p)
    with open(p, encoding="utf-8") as f:
        nodes = json.load(f)
    if not isinstance(nodes, list) or not nodes:
        raise DataMissing("nodes.json 结构异常（应为非空数组）")
    return nodes


def load_edges(T=None):
    """返回 (indptr, indices, weights)，并顺带钉死 dtype（与 P2 验收同口径）。"""
    ensure_import_paths()
    import numpy as np
    T = T or topics_dir()
    p = os.path.join(T, "edges.csr.npz")
    require_files(p)
    z = np.load(p)
    ip, ix, wt = z["indptr"], z["indices"], z["weights"]
    got = "%s/%s/%s" % (ip.dtype, ix.dtype, wt.dtype)
    if got != "int64/int32/float32":
        raise DataMissing("edges.csr.npz dtype 异常：%s（期望 int64/int32/float32）" % got)
    return ip, ix, wt


def load_cluster_labels(D=None):
    """卡簇标签（index/clusters.npy）—— 计算同簇共现计数 cs 用；缺失返回 None。"""
    ensure_import_paths()
    import numpy as np
    p = os.path.join(D or data_dir(), "index", "clusters.npy")
    if not os.path.isfile(p):
        return None
    return np.load(p)


def count_lines(path):
    """返回 (物理行数, 非空行数)；两种口径都报，避免"末尾无换行"把计数判错。"""
    total = nonempty = 0
    with open(path, "rb") as f:
        for line in f:
            total += 1
            if line.strip():
                nonempty += 1
    return total, nonempty


def iter_card_topics(T=None):
    """逐行产出 card_topics.jsonl 记录（流式，内存友好）。"""
    T = T or topics_dir()
    p = os.path.join(T, "card_topics.jsonl")
    require_files(p)
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def scan_pair_counts(pairs, T=None, D=None, mms_of=None, clusters=None):
    """单遍扫描 card_topics.jsonl，统计指定无序对的 (共现书数 c, 同簇共现书数 cs)。

    pairs: iterable of (u, v)；内部归一成 u < v 的无序对。
    clusters: {节点 id: cluster}（取自 nodes.json）—— 计算同簇共现数 cs 必需；None 则 cs 不计算。
    mms_of: 传 True 时额外返回每对命中的卡 mms 列表（用于终审①反例的卡号断言）。
    返回 (cnt, cnt_sc, hits)，三者均以归一化 (a, b) 为键；clusters 缺失时 cnt_sc 为 None。
    """
    labels = load_cluster_labels(D)
    clusters = clusters or {}
    norm = []
    for u, v in pairs:
        a, b = (int(u), int(v)) if int(u) < int(v) else (int(v), int(u))
        if a != b and (a, b) not in norm:
            norm.append((a, b))
    if not norm:
        return {}, None, {}
    # 倒排：源点 a → 目标点列表，避免每张卡遍历全部目标对
    want = {}
    for a, b in norm:
        want.setdefault(a, []).append(b)
    cnt = {k: 0 for k in norm}
    hit_map = {k: [] for k in norm}
    can_sc = labels is not None and bool(clusters)
    cnt_sc = {k: 0 for k in norm} if can_sc else None
    with open(os.path.join(T or topics_dir(), "card_topics.jsonl"), encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            rec = json.loads(line)
            seen = set(rec["topics"])
            hit_here = []
            for a, bs in want.items():
                if a not in seen:
                    continue
                for b in bs:
                    if b in seen:
                        hit_here.append((a, b))
            if not hit_here:
                continue
            lab = int(labels[i]) if can_sc and i < len(labels) else None
            mms = rec.get("mms")
            for k in hit_here:
                cnt[k] += 1
                if can_sc and lab is not None and \
                        clusters.get(k[0]) == clusters.get(k[1]) == lab:
                    cnt_sc[k] += 1
                if mms_of:
                    hit_map[k].append(mms)
    return cnt, cnt_sc, hit_map


# ---------------------------------------------------------------------------
# 主体工具调用（子进程；只读；不触网）
# ---------------------------------------------------------------------------
def run_tool(args, timeout=300, cmd="around"):
    """调用主体 topic_graph.py，返回 (returncode, stdout+stderr)。

    显式注入 TOPIC_LLM=off（默认 off，双保险）—— 回归集不得触网。
    """
    env = dict(os.environ)
    env["TOPIC_LLM"] = "off"
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    tool = os.path.join(ROOT_DIR, "topic_graph.py")
    require_files(tool)
    p = subprocess.run([sys.executable, tool] + [str(a) for a in args],
                       cwd=ROOT_DIR, env=env, timeout=timeout,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# 报告器
# ---------------------------------------------------------------------------
class Reporter:
    """PASS / WARN / FAIL 三态报告器。

    * check()      —— 硬断言：不满足即 FAIL（受守护的既有行为）
    * warn_check() —— 预警断言：不满足记 WARN（**已知未修缺陷，待 R2**），修复后自动转 PASS
    * skip()       —— 前置产物缺失，不计入任何判定
    """

    def __init__(self, tag, title, sources=None):
        self.tag = tag
        self.title = title
        self.sources = sources or {}
        self.n_pass = self.n_fail = self.n_warn = self.n_skip = 0
        self.failures = []
        self.warns = []
        self._sec = None
        print("=== %s — %s ===" % (tag, title))
        print("workdir : %s" % ROOT_DIR)
        print("data-dir: %s" % data_dir())
        print("-" * 72)

    # -- 输出助手 ---------------------------------------------------------
    def section(self, title):
        self._sec = title
        print("\n[%s]" % title)

    def info(self, msg):
        print("  [INFO] %s" % msg)

    def _src(self, source):
        src = self.sources.get(source, source)
        return ("    ↳ 来源: %s" % src) if src else ""

    # -- 三态 -------------------------------------------------------------
    def check(self, name, ok, detail="", source=""):
        if ok:
            self.n_pass += 1
            print("  [PASS] %s%s" % (name, (" | " + detail) if detail else ""))
        else:
            self.n_fail += 1
            self.failures.append(name)
            print("  [FAIL] %s%s" % (name, (" | " + detail) if detail else ""))
            if source:
                print(self._src(source))
        return bool(ok)

    def warn_check(self, name, fixed_ok, detail="", source="", todo="R2"):
        """预警断言：`fixed_ok=True` 表示缺陷已修（PASS）；否则 WARN（不判 FAIL）。

        R2-E 起 R2 已收口，仍留在 warn_check 的条目即「R2 未纳入修复」，todo 写明原因。
        """
        if fixed_ok:
            self.n_pass += 1
            print("  [PASS] %s%s" % (name, (" | " + detail) if detail else ""))
            print("    ↳ 已知缺陷已修复：可把本项从 warn_check 升级为 check() 硬断言")
        else:
            self.n_warn += 1
            self.warns.append(name)
            print("  [WARN] %s%s  ← 已知未修缺陷（%s）" % (
                name, (" | " + detail) if detail else "", todo))
            if source:
                print(self._src(source))
        return bool(fixed_ok)

    def baseline(self, name, actual, reference, note="", source=""):
        """基线漂移报告：与冻结基线参考值一致 → PASS；不一致 → **WARN**（非 FAIL）。

        用途：产物被合法重建（节点表/边表重跑）时，数据相关数字会自然漂移。
        漂移本身不是回归，但必须被看见——WARN 提示复核后可更新 _common.py 的 FROZEN 基线。
        R2-E 起 FROZEN 已升级为 R2 后基线，故文案不再写死 "R1 基线"。
        """
        same = actual == reference
        if same:
            self.n_pass += 1
            print("  [PASS] %s | %s（与冻结基线一致）" % (name, actual))
        else:
            self.n_warn += 1
            self.warns.append("%s（基线漂移）" % name)
            print("  [WARN] %s | 实测 %s ≠ 冻结基线参考 %s%s ← 基线漂移，请复核后更新 FROZEN"
                  % (name, actual, reference, ("；" + note) if note else ""))
            if source:
                print(self._src(source))
        return same

    def skip(self, name, detail=""):
        self.n_skip += 1
        print("  [SKIP] %s%s" % (name, (" | " + detail) if detail else ""))

    # -- 收尾 -------------------------------------------------------------
    def verdict(self):
        return "FAIL" if self.n_fail else ("WARN" if self.n_warn else "PASS")

    def finish(self):
        print("-" * 72)
        if self.n_fail:
            print("失败项：")
            for f in self.failures:
                print("  - %s" % f)
        if self.n_warn:
            print("预警项（已知未修缺陷，待 R2；不计入 FAIL）：")
            for w in self.warns:
                print("  - %s" % w)
        v = self.verdict()
        print("RESULT %s %s pass=%d fail=%d warn=%d skip=%d" % (
            self.tag, v, self.n_pass, self.n_fail, self.n_warn, self.n_skip))
        print("%s: %s (pass=%d fail=%d warn=%d skip=%d)" % (
            self.tag.upper(), v, self.n_pass, self.n_fail, self.n_warn, self.n_skip))
        return 0 if self.n_fail == 0 else 1


def main_guard(tag, title, build, sources=None):
    """统一入口：构造 Reporter → 调 build(reporter) → 异常转 FAIL → 返回退出码。

    任何异常都必须变成 FAIL（回归集绝不允许"崩溃即通过"）。
    """
    R = Reporter(tag, title, sources)
    try:
        build(R)
    except DataMissing as e:
        R.check("前置产物可用", False, str(e))
    except Exception as e:  # noqa: BLE001 —— 兜底：崩溃即 FAIL，并打印栈
        traceback.print_exc()
        R.check("用例可执行（无未捕获异常）", False, "%s: %s" % (type(e).__name__, e))
    return R.finish()


__all__ = [n for n in dir() if not n.startswith("_")]

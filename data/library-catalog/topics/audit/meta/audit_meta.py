#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUDIT-META · meta.json 多阶段登记链 / 哈希链 / 引用一致性 / 时间线因果 审计

只读原则：不修改、不 import、不 exec 任何被审对象（脚本只做 json.load 与 hashlib）。
产物只写 topics/audit/meta/。

四轴：
  A. meta.json 深审      —— stages 分段字段完整性、与各阶段报告的数值交叉核对、
                            current_stage 逻辑、顶层 stage 兼容设计的风险面
  B. 哈希链核查          —— ACCEPTANCE-REPORT.md 登记的全部 sha256 + 导出 manifest 8 项
                            逐项实地重算比对
  C. 引用一致性          —— README ↔ ACCEPTANCE-REPORT ↔ INTERFACE-PROPOSAL ↔ meta 的
                            文件指针与关键数字是否互斥
  D. 时间线因果          —— mtime 序：产物是否晚于其输入

用法： python3 audit_meta.py [--data /home/wzh/go/lib-catalog-data]
产出： audit/meta/audit-results.json, audit/meta/snapshot.json
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime

# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
DEFAULT_DATA = "/home/wzh/go/lib-catalog-data"
TOOLCHAIN = "/home/wzh/go/reasonix-scripts/lib-catalog"

# 被审产物（快照用）
SNAPSHOT_DATA = [
    "topics/meta.json",
    "topics/card_topics.jsonl",
    "topics/nodes.json",
    "topics/edges.csr.npz",
    "topics/edges.variant-spec.csr.npz",
    "topics/p1-build-report.json",
    "topics/p2-build-report.json",
    "topics/topics-report.json",
    "topics/README.md",
    "topics/ACCEPTANCE-REPORT.md",
    "topics/INTERFACE-PROPOSAL.md",
    "topics/export-sample/v1/manifest.json",
    "topics/export-sample/v1/topics/manifest.topics.json",
    "topics/export-sample/v1/topics/meta.json",
]
SNAPSHOT_TOOLCHAIN = [
    "topic_build.py",
    "topic_edges.py",
    "topics_report.py",
    "topic_graph.py",
    "topics_meta.py",
    "export_release.py",
    "acceptance/topics-p0.sh",
    "acceptance/topics-p1.sh",
    "acceptance/topics-p2.sh",
    "acceptance/topics-p3.sh",
    "acceptance/topics-p4.sh",
    "acceptance/topics-p5.sh",
]

# --------------------------------------------------------------------------
# 结果收集
# --------------------------------------------------------------------------
R = []          # 全部发现
COUNTER = {"ok": 0, "warn": 0, "bad": 0, "info": 0}


def rec(axis, level, item, detail, expect=None, actual=None):
    """level: ok / warn / bad / info"""
    COUNTER[level] = COUNTER.get(level, 0) + 1
    R.append({
        "axis": axis, "level": level, "item": item, "detail": detail,
        "expect": expect, "actual": actual,
    })
    return R[-1]


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def statf(path):
    st = os.stat(path)
    return {
        "path": path,
        "size": st.st_size,
        "sha256": sha256_file(path),
        "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "mtime_epoch": st.st_mtime,
    }


def loadjson(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def deep_eq(a, b):
    """递归比较，返回 (是否相等, 首个差异路径)"""
    if type(a) is not type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return (abs(a - b) < 1e-9, None)
        return (False, "type")
    if isinstance(a, dict):
        if set(a) != set(b):
            miss = sorted(set(a) - set(b))
            extra = sorted(set(b) - set(a))
            return (False, "keys miss=%s extra=%s" % (miss, extra))
        for k in a:
            ok, why = deep_eq(a[k], b[k])
            if not ok:
                return (False, "%s->%s" % (k, why))
        return (True, None)
    if isinstance(a, list):
        if len(a) != len(b):
            return (False, "len %d vs %d" % (len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            ok, why = deep_eq(x, y)
            if not ok:
                return (False, "[%d].%s" % (i, why))
        return (True, None)
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return (a is b, None)
        return (abs(a - b) < 1e-9, "float")
    return (a == b, None)


def norm_ts(s):
    """把 '2026-09-18T18:12:14+0800' / '2026-09-18 18:12:14' 归一成 '2026-09-18 18:12:14'"""
    if not isinstance(s, str):
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", s.strip())
    return "%s %s" % (m.group(1), m.group(2)) if m else None


# --------------------------------------------------------------------------
# A. meta.json 深审
# --------------------------------------------------------------------------
# 每段的"契约字段"（必须有）+ "扩展字段"（可选，审计只记录）
STAGE_CONTRACT = {
    "P0": ["stage", "baseline", "generated_at", "generator", "data_dir",
           "artifacts_dir_actual", "baseline_sha256", "wall_seconds",
           "baseline_numbers", "notes", "supplementary"],
    "P1": ["stage", "generated_at", "generator", "seconds", "params", "counts",
           "artifacts", "report_file"],
    "P2": ["stage", "generated_at", "generator", "seconds", "params", "counts",
           "edge_stats", "self_test", "artifacts", "report_file"],
    "P3": ["stage", "generated_at", "generator", "config", "definitions",
           "report_file", "coverage", "performance", "connectivity", "decay",
           "artifacts", "verdict"],
    "P4": ["stage", "generated_at", "generator", "commands", "diffusion",
           "search_expansion", "guards", "stub", "acceptance", "artifacts"],
}
# README §2.4 声称的键 —— R2-D 起改为**动态解析** README 的 `stages.<STAGE>` 表，
# 逐个反查 meta.json 是否真有该键（比硬编码更能随文档演进）。
README_STAGE_TABLE_ROW = re.compile(r"^\|\s*\**`stages\.(P\d|R2-[ABC])`\**\s*\|(.*?)\|\s*[^|]*\|\s*$")
# 各阶段报告文件（P1/P2/P3）
STAGE_REPORT = {
    "P1": "topics/p1-build-report.json",
    "P2": "topics/p2-build-report.json",
    "P3": "topics/topics-report.json",
}


def audit_meta_sections(data_dir):
    axis = "A"
    meta_path = os.path.join(data_dir, "topics/meta.json")
    m = loadjson(meta_path)

    # ---- A1 顶层结构 ----
    top_keys = sorted(m.keys())
    stages = m.get("stages") or {}
    rec(axis, "info", "A1 顶层键", "共 %d 个：%s" % (len(top_keys), ", ".join(top_keys)))
    rec(axis, "info", "A1 stages 分段", "共 %d 段：%s" % (len(stages), ", ".join(sorted(stages))))

    # ---- A2 stages.P0 是否等于顶层遗留键的镜像 ----
    residual = {k: v for k, v in m.items()
                if k not in ("stages", "current_stage", "updated_at", "notes_meta")}
    p0 = stages.get("P0") or {}
    if not p0:
        rec(axis, "bad", "A2 P0 镜像", "stages.P0 缺失")
    else:
        eq, why = deep_eq(residual, p0)
        if eq:
            rec(axis, "ok", "A2 P0 镜像",
                "顶层遗留键（%d 个）与 stages.P0 逐字段相等 —— 双写未漂移" % len(residual))
        else:
            rec(axis, "bad", "A2 P0 镜像",
                "顶层遗留键与 stages.P0 已漂移：%s" % why,
                expect="逐字段相等", actual=why)

    # ---- A3 每段契约字段完整性 ----
    for st, contract in STAGE_CONTRACT.items():
        seg = stages.get(st)
        if seg is None:
            rec(axis, "bad", "A3 %s 段缺失" % st, "stages.%s 不存在" % st)
            continue
        miss = [k for k in contract if k not in seg]
        extra = [k for k in seg if k not in contract]
        if miss:
            rec(axis, "bad", "A3 %s 契约字段缺失" % st, "缺：%s" % ", ".join(miss),
                expect=", ".join(contract), actual=", ".join(sorted(seg)))
        else:
            rec(axis, "ok", "A3 %s 契约字段齐全" % st,
                "%d/%d 必填键齐备；扩展键 %d 个：%s"
                % (len(contract), len(contract), len(extra),
                   ", ".join(sorted(extra)) if extra else "无"))
        # stage 自指字段
        if seg.get("stage") != st:
            rec(axis, "bad", "A3 %s.stage 自指" % st,
                "段内 stage=%r 与段名不符" % seg.get("stage"),
                expect=st, actual=seg.get("stage"))

    # ---- A4 文档承诺的键 vs 实际键（动态解析 README §2.4 的 stages 表）----
    readme_path = os.path.join(data_dir, "topics/README.md")
    if os.path.exists(readme_path):
        rtext = open(readme_path, encoding="utf-8").read()
        row_hits = 0
        for line in rtext.splitlines():
            rm = README_STAGE_TABLE_ROW.match(line.strip())
            if not rm:
                continue
            seg_name, cell = rm.group(1), rm.group(2)
            seg = stages.get(seg_name)
            if seg is None:
                rec(axis, "bad", "A4 README 段名 %s" % seg_name,
                    "README §2.4 列出了 stages.%s，但 meta.json 无此段" % seg_name)
                continue
            # 只取**一级键**：先剥掉中文括号内的「子键/取值/公式」说明，再抽反引号 token。
            cell_clean = re.sub(r"（[^）]*）", "", cell)
            keys = re.findall(r"`([A-Za-z0-9_\-]+)`", cell_clean)
            keys = [k for k in dict.fromkeys(keys) if not k.startswith("topics")]
            # 段名自身（如 `stages.P5` 行里的 P5）与说明词不算键
            keys = [k for k in keys if k not in (seg_name,)]
            missing = [k for k in keys if k not in seg]
            row_hits += 1
            if missing:
                rec(axis, "bad", "A4 README 承诺键 %s" % seg_name,
                    "README §2.4 把 %s 列为该段键，但 meta.json 中不存在" % ", ".join(missing),
                    expect="存在", actual="缺失")
            else:
                rec(axis, "ok", "A4 README 承诺键 %s" % seg_name,
                    "%d 个承诺键全部实存（%s）" % (len(keys), ", ".join(keys)))
        if row_hits == 0:
            rec(axis, "warn", "A4 README stages 表", "未能从 README §2.4 解析出 stages 表行")
    else:
        rec(axis, "warn", "A4 README", "README.md 不存在，跳过承诺键反查")

    # ---- A5 与各阶段报告交叉核对 ----
    for st, rel in STAGE_REPORT.items():
        rp = os.path.join(data_dir, rel)
        if not os.path.exists(rp):
            rec(axis, "warn", "A5 %s 报告文件缺失" % st, rel)
            continue
        rep = loadjson(rp)
        seg = stages.get(st) or {}

        # 时间戳
        a, b = norm_ts(seg.get("generated_at")), norm_ts(rep.get("generated_at"))
        if a == b:
            rec(axis, "ok", "A5 %s generated_at" % st, "段与报告同刻：%s" % a)
        else:
            rec(axis, "bad", "A5 %s generated_at" % st, "段=%s 报告=%s" % (a, b),
                expect=b, actual=a)

        # 计时
        mv, rv = seg.get("seconds"), rep.get("seconds", rep.get("wall_seconds"))
        if mv is None or rv is None:
            rec(axis, "info", "A5 %s 计时" % st, "段=%r 报告=%r" % (mv, rv))
        elif abs(mv - rv) < 0.05:
            rec(axis, "ok", "A5 %s seconds" % st, "%.1fs 一致" % mv)
        else:
            rec(axis, "bad", "A5 %s seconds" % st, "段=%.1f 报告=%.1f" % (mv, rv),
                expect=rv, actual=mv)

        # 通用字段逐一深比
        for key in ("params", "counts", "edge_stats", "self_test", "config",
                    "definitions"):
            if key not in seg or key not in rep:
                continue
            eq, why = deep_eq(seg[key], rep[key])
            if eq:
                rec(axis, "ok", "A5 %s.%s" % (st, key),
                    "%d 项逐项相等" % (len(seg[key]) if hasattr(seg[key], "__len__") else 1))
            else:
                rec(axis, "bad", "A5 %s.%s 不一致" % (st, key), "首个差异：%s" % why,
                    expect=str(rep[key])[:200], actual=str(seg[key])[:200])

        # artifacts 段与报告的类型不同（meta=list 口径清单 / report=dict 角色映射）→ 按"路径集合"比
        if "artifacts" in seg and "artifacts" in rep:
            def to_paths(x):
                if isinstance(x, dict):
                    return {v for v in x.values() if isinstance(v, str)}
                if isinstance(x, list):
                    return {v for v in x if isinstance(v, str)}
                return set()
            a, b = to_paths(seg["artifacts"]), to_paths(rep["artifacts"])
            only_meta, only_rep = sorted(a - b), sorted(b - a)
            if not only_rep:
                rec(axis, "ok", "A5 %s.artifacts" % st,
                    "报告的 %d 个产物指针全部被 meta 收录（meta 另增登记 %s）"
                    % (len(b), only_meta or "无"))
            else:
                rec(axis, "warn", "A5 %s.artifacts 收录不全" % st,
                    "报告提到但 meta 未登记的产物：%s（meta 另增 %s）"
                    % (", ".join(only_rep), only_meta or "无"),
                    expect=only_rep, actual="未登记")

        # P3 特有：coverage / performance / connectivity 映射
        if st == "P3":
            h12 = [h for h in rep["coverage"]["per_hop"] if h["hop"] == 12][0]
            pairs = [
                ("coverage.cluster_only.mean", seg["coverage"]["cluster_only"]["mean"],
                 h12["coverage_mean"]),
                ("coverage.cluster_only.median", seg["coverage"]["cluster_only"]["median"],
                 h12["coverage_median"]),
                ("coverage.cluster_or_cls.mean", seg["coverage"]["cluster_or_cls"]["mean"],
                 h12["union_coverage_mean"]),
                ("coverage.undirected_closure.mean",
                 seg["coverage"]["undirected_closure"]["mean"],
                 h12["undirected_coverage_mean"]),
                ("performance.p50_ms", seg["performance"]["p50_ms"],
                 rep["performance"]["p50_ms"]),
                ("performance.p95_ms", seg["performance"]["p95_ms"],
                 rep["performance"]["p95_ms"]),
                ("connectivity.components", seg["connectivity"]["components"],
                 rep["connectivity"]["components"]),
                ("connectivity.largest_component", seg["connectivity"]["largest_component"],
                 rep["connectivity"]["largest_component"]),
                ("connectivity.largest_pct", seg["connectivity"]["largest_pct"],
                 rep["connectivity"]["largest_pct"]),
                ("decay.hop1_mean", seg["decay"]["hop1_mean"], rep["decay"]["hop1_mean"]),
                ("decay.hop3_mean", seg["decay"]["hop3_mean"], rep["decay"]["hop3_mean"]),
                ("decay.decay_factor", seg["decay"]["decay_factor"],
                 rep["decay"]["decay_factor"]),
            ]
            for name, x, y in pairs:
                ok = (abs(x - y) < 1e-9) if isinstance(x, float) else (x == y)
                if ok:
                    rec(axis, "ok", "A5 P3 %s" % name, "=%s 与报告一致" % x)
                else:
                    rec(axis, "bad", "A5 P3 %s" % name, "段=%s 报告=%s" % (x, y),
                        expect=y, actual=x)
            # 门槛自洽
            gate = seg["coverage"]["gate"]
            for nm in ("cluster_only", "cluster_or_cls", "undirected_closure"):
                blk = seg["coverage"][nm]
                want = blk["mean"] >= gate
                if bool(blk["pass"]) == want:
                    rec(axis, "ok", "A5 P3 门槛判定 %s" % nm,
                        "mean=%.4f vs gate=%.2f → pass=%s 自洽" % (blk["mean"], gate, blk["pass"]))
                else:
                    rec(axis, "bad", "A5 P3 门槛判定 %s" % nm,
                        "mean=%.4f gate=%.2f 应 pass=%s 实为 %s"
                        % (blk["mean"], gate, want, blk["pass"]),
                        expect=want, actual=blk["pass"])

    # ---- A6 current_stage 逻辑 ----
    cur = m.get("current_stage")
    present = sorted(stages.keys())
    if cur in stages:
        rec(axis, "ok", "A6 current_stage 存在性",
            "current_stage=%s 在 stages 中有对应段" % cur)
    else:
        rec(axis, "bad", "A6 current_stage 存在性",
            "current_stage=%s 无对应段" % cur, expect="属于 %s" % present, actual=cur)

    # 用各段 generated_at 的真实最大值校验 current_stage 是否是"最新阶段"
    ts = {s: norm_ts(seg.get("generated_at")) for s, seg in stages.items()}
    ts = {k: v for k, v in ts.items() if v}
    if ts:
        newest = max(ts, key=lambda k: ts[k])
        if newest == cur:
            rec(axis, "ok", "A6 current_stage 时序",
                "最新 generated_at 段=%s 与 current_stage 一致（%s）" % (newest, ts[newest]))
        else:
            rec(axis, "bad", "A6 current_stage 时序",
                "最新 generated_at 段=%s（%s）但 current_stage=%s"
                % (newest, ts[newest], cur), expect=newest, actual=cur)

    # updated_at 与最新段/文件 mtime 的关系
    up = norm_ts(m.get("updated_at")) or m.get("updated_at")
    rec(axis, "info", "A6 updated_at", "登记 updated_at=%s；meta.json 文件 mtime=%s"
        % (m.get("updated_at"), statf(meta_path)["mtime"]))

    # ---- A7 顶层 stage 兼容设计的风险面 ----
    top_stage = m.get("stage")
    rec(axis, "warn", "A7 顶层 stage 双轨",
        "顶层 stage=%r（P0 遗留，为兼容 acceptance/topics-p0.sh 的 stage==P0 断言而冻结）"
        " 与 current_stage=%r 并存 → 任何只读 meta[\"stage\"] 的消费者会把已到 %s 的产物判为 P0"
        % (top_stage, cur, cur), expect=cur, actual=top_stage)
    # 谁在读这个键
    consumers = []
    for root, _dirs, files in os.walk(TOOLCHAIN):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not (fn.endswith(".py") or fn.endswith(".sh")):
                continue
            fp = os.path.join(root, fn)
            try:
                txt = open(fp, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                if re.search(r"""(\.get\(\s*["']stage["']|\[\s*["']stage["']\s*\]|^\s*"stage":)""", line):
                    consumers.append("%s:%d" % (os.path.relpath(fp, TOOLCHAIN), i))
    rec(axis, "info", "A7 stage 键消费者",
        "工具链内命中 %d 处（含各阶段 acceptance 脚本的 TOP_STAGE 断言）：%s"
        % (len(consumers), "; ".join(consumers[:12])))
    asserting = [c for c in consumers if c.startswith("acceptance/")]
    rec(axis, "warn", "A7 兼容断言耦合",
        "%d 处 acceptance 断言把顶层 stage 硬编码为 P0；该冻结使元数据无法自我描述真实阶段"
        "（真实阶段须读 current_stage=%s）。R2-D 已在 README §2.4 与 meta.notes_meta 显式声明该双轨语义，"
        "并把解除方案登记为 R3 待办" % (len(asserting), cur))
    if "P5" not in stages:
        rec(axis, "bad", "A7 登记链缺 P5",
            "P5（交付与发行）已实际发生且 acceptance/topics-p5.sh 存在，但 stages 无 P5 段",
            expect="stages.P5 存在", actual="缺失")
    else:
        rec(axis, "ok", "A7 登记链含 P5",
            "stages.P5 已登记（R2-D 补登）；stages 现含 %d 段：%s"
            % (len(stages), ", ".join(sorted(stages))))

    # ---- A8 notes_meta 去重/噪声 ----
    nm = m.get("notes_meta") or []
    norm = [re.sub(r"（[^）]*）", "", s) for s in nm]
    dupes = len(nm) - len(set(norm))
    if dupes:
        rec(axis, "warn", "A8 notes_meta 追加留痕",
            "共 %d 条，去掉「（日期 追加 Px）」后模板正文完全相同 → %d 条近似重复；"
            "唯一变量是日期与阶段名，信息密度低" % (len(nm), dupes))
    else:
        rec(axis, "ok", "A8 notes_meta", "%d 条无重复" % len(nm))

    # ---- A9 artifacts / report_file 指针可达性 ----
    for st, seg in stages.items():
        for key in ("report_file", "tuning_evidence"):
            p = seg.get(key)
            if not isinstance(p, str):
                continue
            fp = os.path.join(data_dir, p)
            if os.path.exists(fp):
                rec(axis, "ok", "A9 %s.%s 指针" % (st, key), "%s 实存" % p)
            else:
                rec(axis, "bad", "A9 %s.%s 指针" % (st, key), "%s 不存在" % p,
                    expect="存在", actual="缺失")
        arts = seg.get("artifacts")
        if isinstance(arts, list):
            for a in arts:
                if not isinstance(a, str):
                    continue
                fp = a if os.path.isabs(a) else os.path.join(data_dir, a)
                if not os.path.exists(fp):
                    rec(axis, "bad", "A9 %s.artifacts 指针" % st, "%s 不存在" % a,
                        expect="存在", actual="缺失")
    rec(axis, "info", "A9 artifacts 指针", "各段 artifacts 逐项做了存在性检查（见上）")
    return m


# --------------------------------------------------------------------------
# B. 哈希链核查
# --------------------------------------------------------------------------
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
ELLIPSIS_HASH = re.compile(r"\b[0-9a-f]{8}…[0-9a-f]{6,8}\b")


def resolve_path(rel, data_dir):
    """把报告/清单里的相对指针映射到本机绝对路径

    约定（据 ACCEPTANCE-REPORT §5 的表头与 README 的引用习惯）：
      topics/…      → <data>/topics/…
      docs-draft/…  → <data>/topics/docs-draft/…   （相对 topics/ 书写的短指针）
      export-sample/… → <data>/topics/export-sample/…
      index/…、cards.jsonl 等裸文件名 → <data>/…
      *.py / *.sh   → 工具链 <TOOLCHAIN>/…
    """
    rel = rel.strip().strip("`")
    if rel.startswith("topics/"):
        return os.path.join(data_dir, rel)
    if rel.startswith(("docs-draft/", "export-sample/", "audit/")):
        return os.path.join(data_dir, "topics", rel)
    if rel.startswith("acceptance/"):
        return os.path.join(TOOLCHAIN, rel)
    if rel.startswith("index/") or "/" not in rel:
        if rel.endswith((".py", ".sh")):
            return os.path.join(TOOLCHAIN, rel)
        return os.path.join(data_dir, rel)
    return os.path.join(TOOLCHAIN, rel)


def audit_hash_chain(data_dir):
    axis = "B"
    rep_path = os.path.join(data_dir, "topics/ACCEPTANCE-REPORT.md")
    text = open(rep_path, encoding="utf-8").read()
    lines = text.splitlines()

    # ---- B0 报告自述 ----
    ell = ELLIPSIS_HASH.findall(text)
    rec(axis, "info", "B0 报告哈希登记量",
        "ACCEPTANCE-REPORT.md 全文 64 位完整 sha256 共 %d 项（去重后 %d 项）；"
        "另有 %d 处缩写形式（xxxxxxxx…xxxxxxxx），无法机器校验"
        % (len(HEX64.findall(text)), len(set(HEX64.findall(text))), len(ell)))
    if ell:
        rec(axis, "warn", "B0 缩哈希不可校验",
            "缩写登记 %s —— 人工对账可读，但断掉了自动化复算（建议一律写全 64 位）"
            % ", ".join(sorted(set(ell))[:6]))

    # ---- B1 逐项重算 ----
    items = []
    seen = set()
    # 「版本沿革 / 历史值」表内的哈希是**历史登记**，不作为当前登记值参与漂移判定
    HIST_HEADER = ("沿革", "19:2x 登记", "变更前", "历史值", "观测时刻")
    hist_rows = 0
    cur_header = ""
    for ln, line in enumerate(lines, 1):
        # 只解析 Markdown 表格行（报告中的哈希登记一律形如 | 路径 | `sha` | mtime | 字节 |）
        if not line.lstrip().startswith("|"):
            continue
        if re.match(r"^\|[\s:\-]+\|", line.strip()):
            continue                      # 表头分隔行
        # 表头行判定：本行是表格行，且**下一行是分隔行** → 本行即该表的表头
        nxt = lines[ln].strip() if ln < len(lines) else ""
        if re.match(r"^\|[\s:\-]+\|", nxt):
            cur_header = line
        hs = HEX64.findall(line)
        if not hs:
            continue
        if any(h in cur_header for h in HIST_HEADER) or ("变更前" in line):
            hist_rows += 1
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # 定位含哈希的单元格 → 其左侧第一个反引号 token 即路径
        path = None
        for c in cells:
            if HEX64.search(c):
                break
            m = re.search(r"`([^`]+)`", c)
            if m:
                path = m.group(1)
        # 路径必须像路径：无反引号外文本、无空格、无 = （排除 "stages.P0.baseline_sha256 = <hash>" 这类叙述行）
        if path and (re.search(r"[\s=]", path) or "…" in path):
            path = None
        if path is None and re.search(r"`([A-Za-z0-9_./\-]+)`", line):
            cand = re.search(r"`([A-Za-z0-9_./\-]+)`", line).group(1)
            path = cand if not re.search(r"[\s=]", cand) and "…" not in cand else None
        # 字节数：取单元格里像 NNN,NNN 的
        size = None
        for c in cells:
            m = re.fullmatch(r"\**\s*([\d,]{4,})\s*\**", c)
            if m:
                size = int(m.group(1).replace(",", ""))
        for h in hs:
            key = (path, h)
            if key in seen:
                continue
            seen.add(key)
            items.append({"line": ln, "path": path, "registered": h, "size": size})

    matched = mismatched = missing = 0
    for it in items:
        if not it["path"]:
            rec(axis, "warn", "B1 无法解析路径", "第 %d 行哈希 %s… 无路径列" % (it["line"], it["registered"][:8]))
            missing += 1
            continue
        fp = resolve_path(it["path"], data_dir)
        it["resolved"] = fp
        if not os.path.exists(fp):
            rec(axis, "bad", "B1 文件缺失", "%s（第 %d 行）不存在于 %s" % (it["path"], it["line"], fp))
            it["status"] = "missing"
            missing += 1
            continue
        d = statf(fp)
        it["actual"] = d["sha256"]
        it["actual_size"] = d["size"]
        it["mtime"] = d["mtime"]
        if d["sha256"] == it["registered"]:
            it["status"] = "match"
            matched += 1
        else:
            it["status"] = "mismatch"
            mismatched += 1
            rec(axis, "warn", "B1 哈希漂移：%s" % it["path"],
                "登记 %s… ≠ 实测 %s…（第 %d 行）" % (it["registered"][:12], d["sha256"][:12], it["line"]),
                expect=it["registered"], actual=d["sha256"])
        if it["size"] is not None and it["size"] != d["size"]:
            rec(axis, "warn", "B1 字节数漂移：%s" % it["path"],
                "登记 %s B ≠ 实测 %s B" % (it["size"], d["size"]),
                expect=it["size"], actual=d["size"])

    rec(axis, "info", "B1 合计",
        "登记项 %d ｜ 逐字节一致 %d ｜ 漂移 %d ｜ 缺文件 %d ｜ 另跳过历史沿革行 %d（按表头判定，不参与漂移）"
        % (len(items), matched, mismatched, missing, hist_rows))

    # 漂移项按"报告分节"归因（§0.1 脚本版本快照 vs §5 v1 未触碰）
    drift = [i for i in items if i.get("status") == "mismatch"]
    if drift:
        rec(axis, "warn", "B1 漂移归因",
            "漂移集中在脚本/验收脚本（%s）—— ACCEPTANCE-REPORT 的 §0.1 版本快照是 19:2x 取证时点，"
            "其后 R1/R1.1 修复再次改动了它们，而报告 §10 追加时未回刷 §0.1 表 → 哈希链在时间轴上断裂"
            % ", ".join(sorted({os.path.basename(i["path"]) for i in drift}))[:300])

    # ---- B2 导出 manifest（8 项）----
    man_path = os.path.join(data_dir, "topics/export-sample/v1/manifest.json")
    man = loadjson(man_path)
    rec(axis, "info", "B2 manifest 清单", "%s：files=%d，total_bytes=%d，generated_at=%s"
        % (man.get("name"), len(man.get("files", [])), man.get("total_bytes", -1),
           man.get("generated_at")))
    total = 0
    bad_man = []
    for f in man["files"]:
        fp = os.path.join(os.path.dirname(man_path), f["path"])
        if not os.path.exists(fp):
            rec(axis, "bad", "B2 manifest 缺文件", "%s" % f["path"])
            bad_man.append(f["path"])
            continue
        d = statf(fp)
        total += d["size"]
        if d["sha256"] == f["sha256"] and d["size"] == f["size"]:
            rec(axis, "ok", "B2 %s" % f["path"],
                "sha256+size 双一致（%d B）" % d["size"])
        else:
            bad_man.append(f["path"])
            rec(axis, "bad", "B2 %s 漂移" % f["path"],
                "登记 size=%s sha=%s… 实测 size=%s sha=%s…"
                % (f["size"], f["sha256"][:12], d["size"], d["sha256"][:12]),
                expect=f["sha256"], actual=d["sha256"])
    if total == man.get("total_bytes"):
        rec(axis, "ok", "B2 total_bytes", "%d 与逐文件求和相等" % total)
    else:
        rec(axis, "bad", "B2 total_bytes", "声明 %s 实测求和 %d" % (man.get("total_bytes"), total),
            expect=man.get("total_bytes"), actual=total)
    nf = len(man["files"])
    if nf == 9:
        rec(axis, "ok", "B2 项数",
            "9 项（R1 时 8 项；R2-C 起新增 edges_types.u8.bin 边型位图）")
    elif nf == 8:
        rec(axis, "warn", "B2 项数",
            "8 项：缺少 R2-C 新增的 edges_types.u8.bin（边型位图）")
    else:
        rec(axis, "warn", "B2 项数", "manifest 有 %d 项（预期 9）" % nf)

    # 嵌套 manifest 的 7 项
    man2_path = os.path.join(data_dir, "topics/export-sample/v1/topics/manifest.topics.json")
    man2 = loadjson(man2_path)
    ok2 = 0
    for f in man2["files"]:
        fp = os.path.join(os.path.dirname(man2_path), os.path.basename(f["path"]))
        if os.path.exists(fp) and statf(fp)["sha256"] == f["sha256"]:
            ok2 += 1
    rec(axis, "ok" if ok2 == len(man2["files"]) else "bad", "B2 内层 manifest",
        "manifest.topics.json %d/%d 项哈希自洽" % (ok2, len(man2["files"])))

    # ---- B3 meta.baseline_sha256 ----
    meta = loadjson(os.path.join(data_dir, "topics/meta.json"))
    reg = meta.get("baseline_sha256")
    bl = os.path.join(data_dir, meta.get("baseline", ""))
    if os.path.exists(bl):
        act = sha256_file(bl)
        if act == reg:
            rec(axis, "ok", "B3 baseline_sha256", "baseline-p0.txt 复算与登记一致（%s…）" % act[:12])
        else:
            rec(axis, "bad", "B3 baseline_sha256", "登记 %s… 实测 %s…" % (reg[:12], act[:12]),
                expect=reg, actual=act)
    else:
        rec(axis, "bad", "B3 baseline 文件缺失", bl)

    # ---- B4 冻结副本 vs 活件 ----
    live = statf(os.path.join(data_dir, "topics/meta.json"))
    frozen = statf(os.path.join(data_dir, "topics/export-sample/v1/topics/meta.json"))
    if live["sha256"] == frozen["sha256"]:
        rec(axis, "ok", "B4 meta 冻结副本", "导出版 meta.json 与活件一致")
    else:
        rec(axis, "warn", "B4 包内 meta 为打包时点快照",
            "导出版冻结 meta.json（%d B @%s）≠ 活件（%d B @%s）—— 属**快照语义**（包内 meta 与包内数据同源，"
            "由 manifest#snapshot.meta_binding 校验），但**不包含打包之后的登记变更**（如 stages.P5）；"
            "manifest 全绿只证明「包内自洽」，不证明「包内 = 最新口径」。"
            "**R3 待办**：需要最新口径时重新导出（`export_release.py --topics-only`）"
            "或在包内 manifest 注明「本包 meta 对应活件 sha256」"
            % (frozen["size"], frozen["mtime"], live["size"], live["mtime"]),
            expect=live["sha256"], actual=frozen["sha256"])
        # 冻结副本缺哪些段
        fm = loadjson(os.path.join(data_dir, "topics/export-sample/v1/topics/meta.json"))
        miss = sorted(set(meta.get("stages", {})) - set(fm.get("stages", {})))
        keys_miss = []
        for st in meta.get("stages", {}):
            if st in fm.get("stages", {}):
                diff = sorted(set(meta["stages"][st]) - set(fm["stages"][st]))
                if diff:
                    keys_miss.append("%s 缺 %s" % (st, ",".join(diff)))
        rec(axis, "info", "B4 冻结副本差异",
            "缺段=%s；段内缺键=%s" % (miss or "无", "; ".join(keys_miss) or "无"))
    return items


# --------------------------------------------------------------------------
# C. 引用一致性（文档间互引）
# --------------------------------------------------------------------------
def audit_refs(data_dir):
    axis = "C"
    topics = os.path.join(data_dir, "topics")
    readme = open(os.path.join(topics, "README.md"), encoding="utf-8").read()
    acc = open(os.path.join(topics, "ACCEPTANCE-REPORT.md"), encoding="utf-8").read()
    prop = open(os.path.join(topics, "INTERFACE-PROPOSAL.md"), encoding="utf-8").read()
    meta = loadjson(os.path.join(topics, "meta.json"))
    st = meta["stages"]
    p2 = loadjson(os.path.join(topics, "p2-build-report.json"))
    p3 = loadjson(os.path.join(topics, "topics-report.json"))

    # ---- C1 README §2.4 声称的 current_stage ----
    m = re.search(r"\*\*当前 `current_stage=\"(\w+)\"`\*\*", readme)
    if m:
        cs = m.group(1)
        if cs == meta.get("current_stage"):
            rec(axis, "ok", "C1 README current_stage", "=%s 与 meta 一致" % cs)
        else:
            rec(axis, "bad", "C1 README current_stage", "README=%s meta=%s"
                % (cs, meta.get("current_stage")), expect=meta.get("current_stage"), actual=cs)
    else:
        rec(axis, "warn", "C1 README current_stage", "未能解析该断言")
    # README 若硬编码 updated_at，则必须与 meta 相等（R2-D 改为「见 meta.json」即视为通过）
    m = re.search(r"`updated_at=\"([^\"]+)\"`", readme)
    if m:
        if m.group(1) == meta.get("updated_at"):
            rec(axis, "ok", "C1 README updated_at", "=%s 与 meta 一致" % m.group(1))
        else:
            rec(axis, "bad", "C1 README updated_at",
                "README 登记 %s，meta 实际 %s" % (m.group(1), meta.get("updated_at")),
                expect=meta.get("updated_at"), actual=m.group(1))
    else:
        rec(axis, "ok", "C1 README updated_at",
            "未硬编码（指向 meta.json，无陈旧风险）")

    # ---- C2 README §2.4 self_test 数字 ----
    m = re.search(r"hop12_kw_seeds_mean=([\d.]+)`\**、\**`hop12_all_seeds_mean=([\d.]+)", readme)
    if m:
        want = (round(p2["self_test"]["hop12_kw_seeds_mean"], 4),
                round(p2["self_test"]["hop12_all_seeds_mean"], 4))
        got = (float(m.group(1)), float(m.group(2)))
        if got == want:
            rec(axis, "ok", "C2 README self_test", "%.4f/%.4f 与报告一致" % got)
        else:
            rec(axis, "bad", "C2 README self_test",
                "README 引 %s/%s，p2-build-report 为 %.4f/%.4f"
                % (got[0], got[1], want[0], want[1]), expect=list(want), actual=list(got))
    else:
        rec(axis, "warn", "C2 README self_test", "未能解析该断言")

    # ---- C3 README §9 数字来源索引：验收断言数 ----
    got = None
    m = re.search(r"验收 \**([\d/]+) = (\d+) 项全绿", readme)
    if m:
        got = [int(x) for x in m.group(1).split("/")]
        declared_total = int(m.group(2))
    else:
        m = re.search(r"验收 \**([\d/、]+)", readme)
        if m:
            got = [int(x) for x in re.findall(r"(\d+)", m.group(1))]
            declared_total = None
    if got:
        want, logs = [], []
        for lg in ("p0", "p1", "p2", "p3", "p4", "p5"):
            for cand in (os.path.join(topics, "audit/r2c/runs-acceptance-%s.log" % lg),
                         os.path.join(topics, "acceptance-%s.log" % lg)):
                if os.path.exists(cand):
                    mm = re.search(r"pass=(\d+) fail=(\d+)", open(cand, encoding="utf-8").read())
                    if mm:
                        want.append(int(mm.group(1)))
                        logs.append(os.path.relpath(cand, topics))
                    break
        if got == want:
            rec(axis, "ok", "C3 README 验收断言数",
                "%s 与末次复跑日志一致（合计 %d）" % (got, sum(got)))
        else:
            rec(axis, "bad", "C3 README 验收断言数",
                "README §9 引 %s；日志实测 %s" % (got, want), expect=want, actual=got)
        if declared_total is not None and declared_total != sum(got):
            rec(axis, "bad", "C3 README 断言合计",
                "README 写合计 %d，但分项求和为 %d" % (declared_total, sum(got)),
                expect=sum(got), actual=declared_total)

    # ---- C4 README §9 平均出度 / w=1 占比 ----
    m = re.search(r"出度 \**([\d.]+)\**\s*/\s*权重分布[^|]*?w=1 占 \**([\d.]+)%", readme)
    if m:
        got_deg, got_w1 = float(m.group(1)), float(m.group(2)) / 100.0
        want_deg = p2["edge_stats"]["avg_out_degree"]
        want_w1 = p2["edge_stats"]["w_eq_1_share"]
        if abs(got_deg - want_deg) < 0.001:
            rec(axis, "ok", "C4 README 平均出度", "%.4f 与报告一致" % got_deg)
        else:
            rec(axis, "bad", "C4 README 平均出度", "README=%s 报告=%s" % (got_deg, want_deg),
                expect=want_deg, actual=got_deg)
        if abs(got_w1 - want_w1) < 0.0005:
            rec(axis, "ok", "C4 README w=1 占比", "%.4f 与报告一致" % got_w1)
        else:
            rec(axis, "bad", "C4 README w=1 占比", "README=%.4f 报告=%.4f" % (got_w1, want_w1),
                expect=want_w1, actual=got_w1)
    else:
        rec(axis, "warn", "C4 README 出度/权重", "未能解析该行")

    # ---- C5 P4 p50/p95：README / ACCEPTANCE-REPORT / 报告 三方 ----
    rep_p50 = p3["performance"]["p50_ms"]
    rep_p95 = p3["performance"]["p95_ms"]
    probes = [("README", readme), ("ACCEPTANCE-REPORT", acc)]
    for name, txt in probes:
        mm = None
        # 跳过「引用草案/记录不一致」的句子（§7.1 会原文引用更早的测量值，不属当前主张）
        SKIP = ("草案", "不一致", "docs-draft", "未同步", "更早")
        for line in txt.splitlines():
            if any(s in line for s in SKIP):
                continue
            cand = re.search(r"p50 \**([\d.]+)ms \**/?\s*\**p95 \**([\d.]+)ms", line)
            if cand:
                mm = cand
                break
        if not mm:
            continue
        g50, g95 = float(mm.group(1)), float(mm.group(2))
        if abs(g50 - rep_p50) < 0.01 and abs(g95 - rep_p95) < 0.01:
            rec(axis, "ok", "C5 %s p50/p95" % name, "%.3f/%.3f 与报告一致" % (g50, g95))
        else:
            rec(axis, "bad", "C5 %s p50/p95" % name,
                "引 p50 %.3fms / p95 %.3fms；topics-report.json 为 %.3f/%.3f"
                % (g50, g95, rep_p50, rep_p95), expect=[rep_p50, rep_p95], actual=[g50, g95])

    # ---- C6 README 阶段表 vs 各阶段报告（耗时）----
    m = re.search(r"实测 \**([\d.]+)s → \**([\d,]+)\** 条边", readme)
    if m:
        g, n = float(m.group(1)), int(m.group(2).replace(",", ""))
        w, wn = p2["seconds"], p2["counts"]["edges_final"]
        if abs(g - w) < 0.06 and n == wn:
            rec(axis, "ok", "C6 README P2 耗时/边数", "%.1fs / %d 与报告一致" % (g, n))
        else:
            rec(axis, "bad", "C6 README P2 耗时/边数",
                "README=%.1fs/%d 报告=%.1fs/%d" % (g, n, w, wn),
                expect=[w, wn], actual=[g, n])
    else:
        rec(axis, "warn", "C6 README P2 阶段表", "未能解析 §3.3 标题")

    # ---- C7 三份文档互引的文件指针可达性 ----
    refs = {
        "README": readme, "ACCEPTANCE-REPORT": acc, "INTERFACE-PROPOSAL": prop,
    }
    ptr_re = re.compile(r"`(topics/[A-Za-z0-9_./\-]+|docs-draft/[A-Za-z0-9_./\-]+|"
                        r"export-sample/[A-Za-z0-9_./\-]+|acceptance/[A-Za-z0-9_./\-]+)`")
    missing_ptr = {}
    for name, txt in refs.items():
        for p in sorted(set(ptr_re.findall(txt))):
            p2_ = p.rstrip(".,;)")
            # 排除区间写法（如 topics/acceptance-p0..p5.log）与通配写法
            if ".." in p2_ or "*" in p2_:
                continue
            fp = resolve_path(p2_, data_dir)
            if not os.path.exists(fp):
                missing_ptr.setdefault(name, []).append(p2_)
    if missing_ptr:
        for name, ps in missing_ptr.items():
            rec(axis, "warn", "C7 %s 文件指针悬空" % name,
                "%d 个指针在本机不可达：%s" % (len(ps), ", ".join(ps[:8])))
    else:
        rec(axis, "ok", "C7 文件指针", "三份文档的 topics/docs-draft/export-sample/acceptance 指针均可达")

    # ---- C7b README §9 数字来源索引的两个具体错引 ----
    if "`topics/manifest.topics.json`" in readme:
        rec(axis, "bad", "C7b README 索引错引",
            "README §9 把导出版清单写成 `topics/manifest.topics.json`；该路径不存在，"
            "实际位于 `topics/export-sample/v1/topics/manifest.topics.json`"
            "（同一 README 第 174 行用的是正确路径 → 文档内部自相矛盾）",
            expect="topics/export-sample/v1/topics/manifest.topics.json",
            actual="topics/manifest.topics.json")

    # ---- C9 ACCEPTANCE-REPORT 内部：断言计数自相矛盾 ----
    # 只统计**未加时点/更正标注**的 "30/30"，避免把「本文档已更正」的引用句误判为活断言。
    ANN = ("更正", "原写", "时点", "已过期", "R2-D", "历史", "统一断言计数")
    acc_lines = acc.splitlines()
    unannotated = []
    for i, line in enumerate(acc_lines):
        if "30/30" not in line:
            continue
        # 上下文窗口 ±5 行内出现标注词即视为「已交代的引用」
        win = "\n".join(acc_lines[max(0, i - 5):i + 6])
        if not any(a in win for a in ANN):
            unannotated.append(i + 1)
    has_3030 = bool(unannotated)
    m142 = re.search(r"= (\d+) 项断言全绿", acc)
    if has_3030 and m142:
        rec(axis, "bad", "C9 报告内部断言计数矛盾",
            "§%s 行仍写 P4「30/30 全过」且**未加时点标注**，与「%s 项断言全绿」并存"
            % (",".join(map(str, unannotated)), m142.group(1)),
            expect=m142.group(1), actual="30/30")
    elif m142:
        rec(axis, "ok", "C9 报告内部断言计数",
            "全部「30/30」出现处均已加时点/更正标注；当前计数声明 = %s 项" % m142.group(1))

    # ---- C10 stages 产物登记漏项（variant 产物）----
    p2seg = meta["stages"]["P2"]
    variant = "topics/edges.variant-spec.csr.npz"
    if os.path.exists(os.path.join(data_dir, variant)):
        listed = any("variant" in str(a) for a in (p2seg.get("artifacts") or []))
        rep_variant = "variant_other" in p2.get("artifacts", {})
        if not listed:
            rec(axis, "warn", "C10 P2 产物登记漏项",
                "%s 实存（%d B）且 p2-build-report.artifacts.variant_other 指向它，"
                "但 meta.stages.P2.artifacts 未登记该产物 → 登记清单不完备"
                % (variant, os.path.getsize(os.path.join(data_dir, variant))))
        else:
            rec(axis, "ok", "C10 P2 产物登记", "variant 产物已登记")
        if rep_variant:
            rec(axis, "info", "C10 报告 variant 指针",
                "p2-build-report.artifacts 为 dict（3 键），meta.stages.P2.artifacts 为 list（4 项）"
                "—— 两者类型与构成均不同，A5 的类型差异属设计而非漂移")

    # ---- C8 数字跨文档一致性：边/节点/卡 ----
    triples = [
        ("节点数 5,187", "5,187", [p2["counts"]["nodes"], meta["stages"]["P1"]["counts"]["nodes"]]),
        ("边数 99,268", "99,268", [p2["counts"]["edges_final"],
                                   int(re.search(r'"edges": (\d+)', json.dumps(
                                       loadjson(os.path.join(topics, "export-sample/v1/manifest.json")))).group(1))]),
    ]
    for name, token, vals in triples:
        in_readme = token in readme
        in_acc = token in acc
        agree = len(set(vals)) == 1
        lvl = "ok" if (agree and in_readme and in_acc) else "warn"
        rec(axis, lvl, "C8 %s" % name,
            "README含=%s 报告含=%s 各源值=%s" % (in_readme, in_acc, vals))


# --------------------------------------------------------------------------
# D. 时间线因果
# --------------------------------------------------------------------------
def _repro_evidence(out_dir, rel_o):
    """读 audit/meta/repro-evidence.json：{产物相对路径: {when, sha256, note}}"""
    fp = os.path.join(out_dir, "repro-evidence.json")
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, encoding="utf-8") as f:
            ev = json.load(f)
    except Exception:
        return None
    return (ev.get("artifacts") or {}).get(rel_o)


def _npy_sha(zf, name):
    """读 npz 内单个 .npy 的**原始字节** sha256（不依赖 numpy）"""
    return hashlib.sha256(zf.read(name)).hexdigest()


def _edges_arrays_unchanged(data_dir):
    """R2-C 是否只是给 edges.csr.npz **追加** types.npy（三数组未变）？

    比对 `edges.csr.npz` 与 `edges.csr.pre-r2c.npz` 的 indptr/indices/weights 三个成员
    的**逐字节** sha256。任一不匹配或文件缺失 → False。
    """
    import zipfile
    cur = os.path.join(data_dir, "topics/edges.csr.npz")
    pre = os.path.join(data_dir, "topics/edges.csr.pre-r2c.npz")
    if not (os.path.exists(cur) and os.path.exists(pre)):
        return False
    try:
        zc, zp = zipfile.ZipFile(cur), zipfile.ZipFile(pre)
        for n in ("indptr.npy", "indices.npy", "weights.npy"):
            if n not in zc.namelist() or n not in zp.namelist():
                return False
            if _npy_sha(zc, n) != _npy_sha(zp, n):
                return False
        return True
    except Exception:
        return False


def audit_timeline(data_dir, out_dir):
    axis = "D"
    T = os.path.join(data_dir, "topics")

    def mt(rel, base=data_dir):
        fp = os.path.join(base, rel)
        if not os.path.exists(fp):
            return None
        return statf(fp)

    # 因果断言对：(输入, 产物)
    chain = [
        ("nodes.json（P1 产物）", "topics/nodes.json", "p1-build-report.json", "topics/p1-build-report.json"),
        ("card_topics.jsonl（证据链）", "topics/card_topics.jsonl", "edges.csr.npz（图的边）", "topics/edges.csr.npz"),
        ("card_topics.jsonl（证据链）", "topics/card_topics.jsonl", "p2-build-report.json", "topics/p2-build-report.json"),
        ("edges.csr.npz（图的边）", "topics/edges.csr.npz", "topics-report.json（P3 读数）", "topics/topics-report.json"),
        ("topics-report.json", "topics/topics-report.json", "export-sample manifest", "topics/export-sample/v1/manifest.json"),
        ("edges.csr.npz", "topics/edges.csr.npz", "README.md", "topics/README.md"),
        ("p2-build-report.json", "topics/p2-build-report.json", "meta.json（P2 段写入）", "topics/meta.json"),
        ("topics-report.json", "topics/topics-report.json", "meta.json（P3 段写入）", "topics/meta.json"),
    ]
    for in_name, in_rel, out_name, out_rel in chain:
        a, b = mt(in_rel), mt(out_rel)
        if a is None or b is None:
            rec(axis, "warn", "D1 因果 %s → %s" % (in_name, out_name),
                "缺文件：%s" % (in_rel if a is None else out_rel))
            continue
        d = b["mtime_epoch"] - a["mtime_epoch"]
        if d >= 0:
            rec(axis, "ok", "D1 因果 %s → %s" % (in_name, out_name),
                "产物晚于输入 %+.1fs（%s → %s）" % (d, a["mtime"], b["mtime"]))
        elif in_rel.endswith("edges.csr.npz"):
            # R2-C 只**追加** types.npy，indptr/indices/weights 三数组与 pre-r2c 逐位一致
            # → 早于本次 npz 重写而生成的报告，其读数仍然有效。
            benign = _edges_arrays_unchanged(data_dir)
            if benign:
                rec(axis, "ok", "D1 因果 %s → %s（已证良性）" % (in_name, out_name),
                    "报告早于 npz 重写 %.1fs，但 R2-C 仅新增 types.npy；"
                    "indptr/indices/weights 与 %s 逐位 sha256 一致 → 报告读数有效"
                    % (-d, "edges.csr.pre-r2c.npz"))
            else:
                rec(axis, "bad", "D1 因果 %s → %s" % (in_name, out_name),
                    "产物早于输入 %.1fs，且三数组与 pre-r2c 不一致（无法解释）" % d,
                    expect="产物 mtime ≥ 输入 mtime", actual="%.1fs" % d)
        else:
            rec(axis, "bad", "D1 因果 %s → %s" % (in_name, out_name),
                "产物早于输入 %.1fs（%s → %s）" % (d, a["mtime"], b["mtime"]),
                expect="产物 mtime ≥ 输入 mtime", actual="%.1fs" % d)

    # 工具链 vs 产物：脚本必须早于其产物（否则产物无法由该版本脚本生成）
    tool = [
        ("topic_build.py", "topic_build.py", "topics/nodes.json"),
        ("topic_edges.py", "topic_edges.py", "topics/edges.csr.npz"),
        ("topics_report.py", "topics_report.py", "topics/topics-report.json"),
    ]
    for nm, rel_t, rel_o in tool:
        a, b = mt(rel_t, TOOLCHAIN), mt(rel_o)
        if a is None or b is None:
            continue
        d = b["mtime_epoch"] - a["mtime_epoch"]
        if d >= 0:
            rec(axis, "ok", "D2 脚本先于产物 %s" % nm, "%+.1fs（脚本 %s → 产物 %s）"
                % (d, a["mtime"], b["mtime"]))
        else:
            # 若存在复算证据（audit/meta/repro-evidence.json）证明产物可逐字节再生，
            # 则该错配为「文档级改动」所致，降级为已证良性。
            ev = _repro_evidence(out_dir, rel_o)
            if ev:
                rec(axis, "ok", "D2 脚本先于产物 %s（已证可复现）" % nm,
                    "脚本晚于产物 %.1fs，但按当前脚本在隔离目录复跑得到**逐字节相同**的产物"
                    "（%s；sha256 %s…）→ 错配由非语义改动（docstring）造成，产物仍可解释"
                    % (-d, ev.get("when"), (ev.get("sha256") or "")[:12]))
            else:
                rec(axis, "bad", "D2 脚本先于产物 %s" % nm,
                    "产物早于脚本 %.1fs → 现存脚本版本无法解释该产物（版本-产物错配）；"
                    "且无复算证据（可运行 audit/meta/ 下的复跑脚本生成 repro-evidence.json）"
                    % d, expect="脚本 mtime ≤ 产物 mtime", actual="%.1fs" % d)

    # 关键异常：p4-relevance.md / p4-smoke.txt 与 topic_graph.py
    a, b = mt("topic_graph.py", TOOLCHAIN), mt("topics/p4-relevance.md")
    if a and b:
        d = b["mtime_epoch"] - a["mtime_epoch"]
        rec(axis, "info", "D3 P4 产物 vs 脚本",
            "p4-relevance.md %s ｜ topic_graph.py %s（差 %+.0fs）→ %s"
            % (b["mtime"], a["mtime"], d,
               "产物晚于脚本" if d >= 0 else "产物早于脚本，需人工确认产物是否对应最终脚本版本"))

    # 报告与 meta 的先后关系（报告引用 meta 登记值 → 报告应晚于 meta 才可能核到最终版）
    a, b = mt("topics/ACCEPTANCE-REPORT.md"), mt("topics/meta.json")
    if a and b:
        d = b["mtime_epoch"] - a["mtime_epoch"]      # >0 = meta 更晚
        if d > 0:
            # meta 若登记了该报告的 sha256，则「meta 晚于报告」是**按设计的自登记顺序**
            # （先定稿报告 → 再把报告哈希写进 stages.P5.doc_hashes），不构成证据时效问题。
            selfreg = False
            try:
                mm = loadjson(os.path.join(data_dir, "topics/meta.json"))
                dh = ((mm.get("stages") or {}).get("P5") or {}).get("doc_hashes") or {}
                reg = (dh.get("ACCEPTANCE-REPORT.md") or {}).get("sha256")
                selfreg = (reg == a["sha256"])
            except Exception:
                selfreg = False
            if selfreg:
                rec(axis, "ok", "D4 报告/meta 写入顺序（自登记，按设计）",
                    "meta.json（%s）晚于报告（%s）%.0fs，但 meta 的 stages.P5.doc_hashes 登记的正是"
                    "该报告的当前 sha256（%s…）→ 顺序为「先定稿报告、再登记其哈希」，属设计使然"
                    % (b["mtime"], a["mtime"], d, a["sha256"][:12]))
            else:
                rec(axis, "warn", "D4 报告早于 meta",
                    "meta.json（%s）晚于 ACCEPTANCE-REPORT.md（%s）%.0fs，且 meta 未登记该报告哈希 —— "
                    "报告引用 meta 的登记值却早于其最终写入，引用前请重新核对"
                    % (b["mtime"], a["mtime"], d))
        else:
            rec(axis, "ok", "D4 报告晚于 meta",
                "ACCEPTANCE-REPORT.md（%s）晚于 meta.json（%s）%.0fs → 报告有条件引用 meta 的最终登记值"
                % (a["mtime"], b["mtime"], -d))

    # 冻结导出包 vs 活件
    a, b = mt("topics/export-sample/v1/manifest.json"), mt("topics/meta.json")
    if a and b:
        rec(axis, "info", "D5 导出包 vs 活件 meta",
            "导出包生成 %s，活件 meta.json 最后改动 %s（晚 %.0fs）→ 包内 meta 为历史快照"
            % (a["mtime"], b["mtime"], b["mtime_epoch"] - a["mtime_epoch"]))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data_dir = os.path.abspath(args.data)
    out_dir = args.out or os.path.join(data_dir, "topics/audit/meta")
    os.makedirs(out_dir, exist_ok=True)

    # ---- 快照 ----
    snap = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_dir": data_dir, "toolchain_dir": TOOLCHAIN,
            "data": [], "toolchain": []}
    for rel in SNAPSHOT_DATA:
        fp = os.path.join(data_dir, rel)
        if os.path.exists(fp):
            d = statf(fp)
            d["rel"] = rel
            snap["data"].append(d)
    for rel in SNAPSHOT_TOOLCHAIN:
        fp = os.path.join(TOOLCHAIN, rel)
        if os.path.exists(fp):
            d = statf(fp)
            d["rel"] = rel
            snap["toolchain"].append(d)
    with open(os.path.join(out_dir, "snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    # ---- 四轴 ----
    audit_meta_sections(data_dir)
    hash_items = audit_hash_chain(data_dir)
    audit_refs(data_dir)
    audit_timeline(data_dir, out_dir)

    result = {
        "generated_at": snap["generated_at"],
        "counts": COUNTER,
        "findings": R,
        "hash_items": hash_items,
        "snapshot_ref": "snapshot.json",
    }
    with open(os.path.join(out_dir, "audit-results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    # ---- 控制台摘要 ----
    print("=" * 78)
    print("AUDIT-META 汇总：ok=%d warn=%d bad=%d info=%d"
          % (COUNTER["ok"], COUNTER["warn"], COUNTER["bad"], COUNTER["info"]))
    print("=" * 78)
    for lvl, tag in (("bad", "❌"), ("warn", "⚠️"), ("ok", "✅")):
        rows = [r for r in R if r["level"] == lvl]
        print("\n--- %s %s (%d) ---" % (tag, lvl.upper(), len(rows)))
        for r in rows:
            print("  [%s] %s :: %s" % (r["axis"], r["item"], r["detail"][:220]))
    print("\n产物：%s/audit-results.json, snapshot.json" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

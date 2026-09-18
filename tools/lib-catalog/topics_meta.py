#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topics_meta.py — topics/meta.json 多阶段口径登记器（P0/P1/P2…）

背景：meta.json 由 P0 建立（顶层扁平结构，`stage`/`baseline`/`baseline_numbers`…）。
P0 验收脚本 `acceptance/topics-p0.sh` 断言顶层 `stage == "P0"`，因此本工具**不动顶层既有键**，
只增量维护 `stages.<STAGE>` 分段与 `current_stage`/`updated_at`，兼容旧验收脚本。

用法：
  python3 topics_meta.py --stage P1 [--data DIR] [--meta PATH] [--report PATH] [--dry-run]
  python3 topics_meta.py --stage P2 --report p2-build-report.json --extra-file extra.json

- P0：把顶层既有键镜像进 `stages.P0`（首次运行自动迁移）。
- P1：从 `p1-build-report.json` 提取 params/counts/freq_stats，噪声率从 `p1-sample50.txt` 判决列统计。
- P2：从 `p2-build-report.json` 提取 params/counts/edge_stats/self_test（键名由 topic_edges.py 约定）。
- P3：从 `topics-report.json`（topics_report.py 产出）提取三口径覆盖/性能/连通/衰减摘要；
  裁定文本用 `--extra '{"verdict":"..."}'` 注入。
- P4：查询编排（topic_graph.py）命令面/扩散口径/护栏/存根/近词扩展说明（无需 report 文件）。
- `--extra`/`--extra-file`：追加自定义键（JSON 字符串或 JSON 文件）。
所有写入为「读-改-写」，保持 UTF-8 + indent=2 且 ensure_ascii=False。
"""
import argparse
import json
import os
import re
import time

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")
REPORT_FILES = {"P1": "p1-build-report.json", "P2": "p2-build-report.json", "P3": "topics-report.json"}
LEGACY_TOP_KEYS = (
    "stage", "baseline", "generated_at", "generator", "data_dir",
    "artifacts_dir_actual", "baseline_sha256", "wall_seconds",
    "baseline_numbers", "notes", "supplementary",
)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def noise_from_sample(path):
    """从 p1-sample50.txt 的 verdict 列统计噪声率（列：stratum/id/term/type/freq/cluster/cls/sources/verdict/reason）。"""
    if not os.path.exists(path):
        return None
    total = noisy = 0
    bad = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 9:
                continue
            verdict = cols[8].strip()
            if not verdict or verdict == "verdict":
                continue
            total += 1
            if verdict != "正常":
                noisy += 1
                bad.append({"stratum": cols[0], "id": cols[1], "term": cols[2],
                            "type": cols[3], "verdict": verdict, "reason": cols[9] if len(cols) > 9 else ""})
    if not total:
        return None
    return {"n": total, "noisy": noisy, "noise_rate": round(noisy / total, 4),
            "method": "50 词分层抽检（高/中/低频分层，人工判定）",
            "file": "topics/p1-sample50.txt", "noisy_items": bad}


def build_p1(report, data_dir):
    out = {"stage": "P1",
           "generated_at": report.get("generated_at"),
           "generator": "python3 topic_build.py --data %s" % data_dir,
           "seconds": report.get("seconds"),
           "params": report.get("params"),
           "counts": report.get("counts"),
           "freq_stats": report.get("freq_stats"),
           "artifacts": ["topics/nodes.json", "topics/p1-build-report.json",
                         "topics/p1-sample50.txt", "topics/p1-build.log"]}
    ns = noise_from_sample(os.path.join(data_dir, "topics", "p1-sample50.txt"))
    if ns:
        out["noise_sample"] = {k: ns[k] for k in ("n", "noisy", "noise_rate", "method", "file")}
        out["noise_rate"] = ns["noise_rate"]
        out["noisy_items"] = ns["noisy_items"]
    return out


def build_p2(report, data_dir):
    out = {"stage": "P2",
           "generated_at": report.get("generated_at"),
           "generator": "python3 topic_edges.py --data %s" % data_dir,
           "seconds": report.get("seconds"),
           "params": report.get("params"),
           "counts": report.get("counts"),
           "edge_stats": report.get("edge_stats"),
           "self_test": report.get("self_test"),
           "artifacts": ["topics/edges.csr.npz", "topics/card_topics.jsonl",
                         "topics/p2-build-report.json", "topics/p2-build.log"]}
    return {k: v for k, v in out.items() if v is not None}


def build_p3(report, data_dir):
    """P3 段：三口径覆盖 + 性能 + 连通/衰减摘要 + 裁定文本（裁定由 --extra 注入 verdict）。"""
    cov = report.get("coverage") or {}
    perf = report.get("performance") or {}
    cns = report.get("connectivity") or {}
    dec = report.get("decay") or {}
    f, fu, fud = cov.get("final") or {}, cov.get("final_union") or {}, cov.get("final_undirected") or {}
    out = {"stage": "P3",
           "generated_at": report.get("generated_at"),
           "generator": "python3 topics_report.py --data %s --samples 400 --hops 12 --seed 42 (见 config)" % data_dir,
           "config": report.get("config"),
           "definitions": report.get("definitions"),
           "report_file": "topics/topics-report.json",
           "coverage": {
               "gate": f.get("gate"),
               "cluster_only": {"mean": f.get("coverage_mean"), "median": f.get("coverage_median"),
                                "pass": f.get("pass"), "role": "严格观察项（与 v1 基线 0.902 基本持平）"},
               "cluster_or_cls": {"mean": fu.get("coverage_mean"), "median": fu.get("coverage_median"),
                                  "pass": fu.get("pass"), "role": "硬门槛口径（§4-P3 原文「主簇或分类」）"},
               "undirected_closure": {"mean": fud.get("coverage_mean"), "median": fud.get("coverage_median"),
                                      "pass": fud.get("pass"), "role": "方向性诊断列"},
               "denominators": cov.get("denominators"),
           },
           "performance": {"p50_ms": perf.get("p50_ms"), "p95_ms": perf.get("p95_ms"),
                           "target_ms": perf.get("target_ms"), "pass": perf.get("pass")},
           "connectivity": cns,
           "decay": {k: dec.get(k) for k in ("decay_factor", "hop1_mean", "hop3_mean",
                                             "mean_edge_weight_global", "mean_edge_weight_on_best_paths")},
           "artifacts": ["topics/topics-report.json", "topics/topics-report.txt",
                         "topics/topics-report-allseed.json", "topics/acceptance-p3.log"]}
    return {k: v for k, v in out.items() if v is not None}


def build_p4(report, data_dir):
    """P4 段：查询编排（topic_graph.py）的命令面/扩散口径/护栏/存根与近词扩展说明。"""
    return {
        "stage": "P4",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "python3 topic_graph.py（查询编排）+ acceptance/topics-p4.sh（验收）",
        "commands": {
            "search": "主题检索：词面匹配（整词精确 exact / 查询 token 精确 token / 前缀 prefix / 子串 substr）"
                      "× log1p(freq)；不加载书卡",
            "around": "加权扩散邻域 + 分层输出 + card_topics 反查书证据（抽书卡样例）",
            "graph": "JSON 子图 {nodes:[{id,term,type,cluster,w}], edges:[{src,dst,w}], stats}",
            "summarize": "LLM 接口存根 summarize_topic_region(region)->str（region 结构与 INTERFACE-PROPOSAL.md 对齐）",
        },
        "diffusion": {"rule": "w_hop = w_parent × edge_w × 0.86", "threshold": 0.05,
                      "budget_nodes": 50000, "hops_default": 2, "hops_max": 12,
                      "note": "0.86 沿用 §3.4/v1 实测值，可用 --decay 覆盖（interface 待决 #11）"},
        "search_expansion": {
            "when": "--expand auto（默认）：查询本身不是主题词表词（无整词精确命中，含零命中）时启用",
            "path": "① 词面（exact/token/prefix/substr，已有）→ ② TF-IDF 近词扩展（新增）："
                    "复用 v1 索引 index/tfidf.npz（与 catalog_vector.Index.q_kw 同口径：token 计数×idf、查询向量 L2 归一、X@qᵀ 余弦）"
                    "→ 取 top --expand-cards（默认 200）张相关书 → 聚合其 card_topics top-5 主题 → 映射回主题节点",
            "output": "--expand-cards/--expand-top 可调；输出 src=tfidf-expand 标注来源，并给出 n_support_cards 与支持书 mms（--json 全量）",
            "verified": "抽测 3 条非词表查询（机器学习 入门 / 量子 科普 / 人工智能 伦理）均返回相关主题，见 topics/p4-smoke.txt",
        },
        "guards": {"hops_out_of_range": "exit 1（提示 1..12）", "topic_id_out_of_range": "exit 1（提示有效范围）",
                   "strict_llm": "TOPIC_LLM 非 off/mock 且未实现时 exit 3（--strict-llm）",
                   "llm_default": "TOPIC_LLM 未设置 = off（纯结构化占位，不触网）"},
        "stub": {"signature": "summarize_topic_region(region: dict) -> str",
                 "deterministic": True, "network": "无（静态检查：无 requests/urllib/http/socket/url 调用面）",
                 "placeholder_fields": ["扩散规则", "区域规模（主题数/证据书数）", "权重分布 min/中位/max", "层级分布", "代表主题", "证据书样例"]},
        "acceptance": "acceptance/topics-p4.sh（四命令 exit0 / 手算扩散 1-2 跳 / 存根确定性 / 无网络 / 护栏 / JSON 结构）",
        "artifacts": ["topics/p4-smoke.txt", "topics/acceptance-p4.log"],
    }


def main():
    ap = argparse.ArgumentParser(description="topics/meta.json 多阶段口径登记器")
    ap.add_argument("--stage", required=True, choices=["P0", "P1", "P2", "P3", "P4"])
    ap.add_argument("--data", default=DATA_DEFAULT)
    ap.add_argument("--meta", default=None, help="默认 <data>/topics/meta.json")
    ap.add_argument("--report", default=None, help="构建报告 JSON（P1/P2）")
    ap.add_argument("--extra", default=None, help="额外键 JSON 字符串")
    ap.add_argument("--extra-file", default=None, help="额外键 JSON 文件")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data_dir = os.path.abspath(os.path.expanduser(args.data))
    meta_path = args.meta or os.path.join(data_dir, "topics", "meta.json")
    meta = load_json(meta_path, default={}) or {}

    # 首次运行：把顶层既有键镜像进 stages.P0（不动顶层）
    stages = meta.get("stages") or {}
    if "P0" not in stages:
        mirrored = {k: meta[k] for k in LEGACY_TOP_KEYS if k in meta}
        if mirrored:
            stages["P0"] = mirrored

    if args.stage == "P0":
        section = {k: meta[k] for k in LEGACY_TOP_KEYS if k in meta}
    elif args.stage == "P4":
        section = build_p4(None, data_dir)
    else:
        report_path = args.report or os.path.join(data_dir, "topics", REPORT_FILES[args.stage])
        report = load_json(report_path)
        if report is None:
            raise SystemExit("[ERROR] 构建报告不存在: %s" % report_path)
        section = {"P1": build_p1, "P2": build_p2, "P3": build_p3}[args.stage](report, data_dir)
        section.setdefault("report_file", os.path.relpath(report_path, data_dir))

    extra = {}
    if args.extra_file:
        loaded = load_json(args.extra_file, {})
        if isinstance(loaded, dict):
            extra.update(loaded)
        else:  # 列表等非 dict 载荷：以文件名（去扩展名）为键整体挂载
            key = os.path.splitext(os.path.basename(args.extra_file))[0]
            extra[key] = loaded
    if args.extra:
        extra.update(json.loads(args.extra))
    section.update(extra)

    stages[args.stage] = section
    meta["stages"] = stages
    meta["current_stage"] = args.stage
    meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta.setdefault("notes_meta", []).append(
        "多阶段结构说明：顶层既有键为 P0 遗留（保持兼容 acceptance/topics-p0.sh 的 stage==P0 断言）；"
        "各阶段口径以 stages.<STAGE> 为准。本结构由 topics_meta.py 维护（%s 追加 %s）。"
        % (time.strftime("%Y-%m-%d %H:%M"), args.stage))

    if args.dry_run:
        print(json.dumps(section, ensure_ascii=False, indent=2)[:2000])
        return 0
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("[meta] %s <- stages.%s | current_stage=%s | noise_rate=%s"
          % (meta_path, args.stage, args.stage, section.get("noise_rate", "-")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

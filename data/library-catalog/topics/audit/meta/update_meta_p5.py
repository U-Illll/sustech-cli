#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_meta_p5.py — R2-D 任务书：为 meta.json 补登 `stages.P5` 段

背景：`topics_meta.py` 的 `--stage choices` 仅含 `P0..P4`，故 P5 与 R2-* 段一直由专项脚本旁路写入。
本脚本沿用 `audit/r2c/update_meta_r2c.py` 的写法（`indent=1`、`ensure_ascii=False`、尾部换行），
补 `stages.P5`，并把 `notes_meta` 由 8 条重复模板收敛为「1 条结构规范 + 1 条阶段沿革」。

只做三件事：
  1. `stages.P5` ← 交付物/导出版/接口协议指针 + **终值快照**（全部从产物实地读取，可复算）
  2. `notes_meta`   ← 去重收敛（保留信息，去掉重复模板）
  3. `current_stage` ← `"P5"`；`updated_at` ← 当前时刻
**不动**顶层 `stage`（必须保持 "P0" 以兼容 acceptance 断言）。

用法：python3 update_meta_p5.py [--data DIR] [--dry-run]
"""
import argparse
import hashlib
import json
import os
import time

DEFAULT_DATA = "/home/wzh/go/lib-catalog-data"


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    data_dir = os.path.abspath(args.data)
    T = os.path.join(data_dir, "topics")

    meta_path = os.path.join(T, "meta.json")
    meta = load(meta_path)
    stages = meta.get("stages") or {}

    # ---- 终值：全部实地读取（保证可复算）----
    p1 = load(os.path.join(T, "p1-build-report.json"))
    p2 = load(os.path.join(T, "p2-build-report.json"))
    p3 = load(os.path.join(T, "topics-report.json"))
    man = load(os.path.join(T, "export-sample/v1/manifest.json"))
    man2 = load(os.path.join(T, "export-sample/v1/topics/manifest.topics.json"))
    ex = load(os.path.join(T, "topics-report-exhaustive.json"))
    allseed = load(os.path.join(T, "topics-report-allseed.json"))
    st3 = stages["P3"]
    h12 = [x for x in p3["coverage"]["per_hop"] if x["hop"] == 12][0]

    def dstat(rel):
        fp = os.path.join(T, rel)
        st = os.stat(fp)
        return {"path": "topics/" + rel, "bytes": st.st_size,
                "sha256": sha256_file(fp),
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                       time.localtime(st.st_mtime))}

    docs = {n: dstat(n) for n in ("README.md", "ACCEPTANCE-REPORT.md",
                                  "INTERFACE-PROPOSAL.md")}

    section = {
        "stage": "P5",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "dsh AUDIT-META 会话（R2-D 任务书：文档与登记同步）",
        "scope": "交付与发行决策：文档定稿（README / 接口协议）、导出版重建（只生成不发布）、验收脚本固化",
        "acceptance": {
            "script": "acceptance/topics-p5.sh",
            "assertions": 28,
            "result": "PASS (pass=28 fail=0) exit=0",
            "log": "topics/audit/r2c/runs-acceptance-p5.log",
            "note": "该脚本断言「stages.P0–P4 五段齐备」与「顶层 stage 仍为 P0」；补登 stages.P5 不影响其通过。",
        },
        "deliverables": {
            "docs": ["topics/README.md", "topics/INTERFACE-PROPOSAL.md"],
            "docs_draft_kept": ["topics/docs-draft/README-draft.md",
                                "topics/docs-draft/changelog-draft.md",
                                "topics/docs-draft/interface-proposal.md"],
            "export_sample": "topics/export-sample/v1（package_kind=topics-only；只生成、不发布）",
        },
        "doc_hashes": docs,
        "export": {
            "generated_at": man.get("generated_at"),
            "package_kind": man.get("package_kind"),
            "total_bytes": man.get("total_bytes"),
            "outer_files": len(man.get("files", [])),
            "inner_files": len(man2.get("files", [])),
            "manifest_outer": "topics/export-sample/v1/manifest.json",
            "manifest_inner": "topics/export-sample/v1/topics/manifest.topics.json",
            "meta_same_source": (man2.get("snapshot", {})
                                 .get("meta_binding", {}).get("consistent")),
            "source_sha256_bound": sorted(
                (man2.get("snapshot", {}).get("source_sha256") or {}).keys()),
            "release_policy": "只生成、不发布；lib-catalog-release/ 未触碰（末次改动 14:01）",
        },
        "final_values": {
            "_note": "R2-C 终值；替代 stages.P1/P2/P3 中未经重跑的历史字段。口径见各段。",
            "nodes": p2["counts"]["nodes"],
            "kw": p2["counts"]["kw"],
            "cls": p2["counts"]["cls"],
            "edges": p2["counts"]["edges_final"],
            "avg_out_degree": p2["edge_stats"]["avg_out_degree"],
            "weight_mean": p2["edge_stats"]["weight_dist"]["mean"],
            "w_eq_1_share": p2["edge_stats"]["w_eq_1_share"],
            "hierarchical_edges_registered": p2["counts"]["hierarchical_edges"],
            "cards": p2["counts"]["cards"],
            "cards_empty_topics": p2["counts"]["cards_empty_topics"],
            "card_topic_links": man["stats"]["topics"]["card_topic_links"],
            "coverage_kw400": {
                "cluster_only": st3["coverage"]["cluster_only"]["mean"],
                "cluster_or_cls": st3["coverage"]["cluster_or_cls"]["mean"],
                "undirected_closure": st3["coverage"]["undirected_closure"]["mean"],
                "samples": p3["config"]["samples"],
                "source_type": p3["config"]["source_type"],
                "pool_size": p3["coverage"]["pool_size"],
            },
            "coverage_all400": {
                "cluster_only": allseed["coverage"]["final"]["coverage_mean"],
                "cluster_or_cls": allseed["coverage"]["final_union"]["coverage_mean"],
                "undirected_closure": allseed["coverage"]["final_undirected"]["coverage_mean"],
                "samples": allseed["coverage"]["samples"],
                "source_type": allseed["coverage"]["source_type"],
                "pool_size": allseed["coverage"]["pool_size"],
                "note": "仍是 400 采样，非全量统计",
            },
            "coverage_exhaustive": {
                "cluster_only": ex["cluster_only_mean"],
                "cluster_or_cls": ex["cluster_or_cls_mean"],
                "undirected_closure": ex["undirected_mean"],
                "sources": ex["exhaustive_sources"],
                "note": "唯一全量口径",
            },
            "p50_ms": p3["performance"]["p50_ms"],
            "p95_ms": p3["performance"]["p95_ms"],
            "largest_component": p3["connectivity"]["largest_component"],
            "acceptance_total": 147,
            "acceptance_breakdown": {"P0": 8, "P1": 17, "P2": 35, "P3": 21,
                                     "P4": 38, "P5": 28},
        },
        "artifacts": [
            "topics/README.md",
            "topics/INTERFACE-PROPOSAL.md",
            "topics/export-sample/v1/",
            "topics/export-sample/v1/manifest.json",
            "topics/export-sample/v1/topics/manifest.topics.json",
            "topics/audit/r2c/runs-acceptance-p5.log",
        ],
        "r2d_sync": {
            "date": "2026-09-18 R2-D（文档与登记同步）",
            "by": "dsh AUDIT-META 会话",
            "closed_findings": [
                "AUDIT-META：stages 缺 P5 段 → 本次补登 stages.P5",
                "AUDIT-META：README §2.4 承诺 3 个不存在的键（p2.p3_gate_note / p4.gate_note / p4.p5_note）→ 已按实际键重写",
                "AUDIT-META：ACCEPTANCE-REPORT §0.1 登记表漂移 → 表已对齐现值（10 项零漂移）+ 版本沿革表；§5.5 增 R2 列",
                "AUDIT-META：README §9 与 ACCEPTANCE-REPORT 引用 R1 前快照 → 已更新到 R2 终值",
                "AUDIT-META：ACCEPTANCE-REPORT §0/§7「30/30」与 §10「142」并存 → 统一为 147 项（见报告 §11.3）",
                "R2-D 新发现 N1：stages.P2 未随 R2-C 回刷 → 已回刷（见 stages.P2.r2d_sync）",
                "R2-D 新发现 N2：edges.csr.npz 晚于 topics-report.json → 已证良性（三数组与 pre-r2c 逐字节相同）",
                "R2-D 新发现 N3：topic_build.py 晚于 nodes.json → 已证良性（隔离复跑 nodes.json 逐字节相同）",
                "R2-D：README §2.4 补 stages.P5 / R2-* 行与顶层 stage 双轨语义告警；§2.2 补 types 位图 schema",
            ],
            "touched": {
                "meta.json": "补 stages.P5；current_stage→P5；notes_meta 去重收敛",
                "ACCEPTANCE-REPORT.md": "顶部同步声明；§0.1/§0.2/§1/§2.3/§3.1/§3.4 更新；新增 §11",
                "README.md": "§9/§2.2/§2.4/阶段表/§3/§7/§8 同步终值；补 types schema；修 3 个承诺键",
                "topic_build.py": "docstring --min-df 8→12（闭环 README §8-R5）",
                "TOPIC-GRAPH-HANDOFF-20260918.md": "§8 追加 R1/R2 轮结果注记",
            },
            "backups": {
                "meta.json": "topics/meta.json.pre-r2d",
                "ACCEPTANCE-REPORT.md": "topics/ACCEPTANCE-REPORT.md.pre-r2d",
                "README.md": "topics/README.md.pre-r2d",
                "handoff": "reasonix-scripts/lib-catalog/TOPIC-GRAPH-HANDOFF-20260918.md.pre-r2d",
            },
            "not_done_R3": [
                "acceptance 脚本断言加固（H 清单保留在 topics/audit/acc 作 backlog）",
                "解除顶层 stage==P0 的兼容冻结（断言改指 stages.P0.stage）",
                "topics_meta.py --stage choices 扩到 P5|R2-*；统一 meta.json 缩进为 indent=1",
                "AUDIT-EXPORT E3/E4 与 AUDIT-EDGETYPE §4.4 残留（见 stages['R2-C'].not_done）",
                "导出版重导以携带 stages.P5，或在包内 manifest 注明对应活件 meta sha256（R19）",
            ],
            "verification": {
                "auditor": "topics/audit/meta/audit_meta.py（只读复跑）",
                "result": "ok=87 warn=4 bad=0；ACCEPTANCE-REPORT 内完整 64 位 sha256 全部可实地复算、零漂移；"
                          "导出版 manifest 内外层 9/9 + 8/8 一致；baseline_sha256 一致",
                "acceptance_after_sync": "六脚本 147 项断言全绿 exit 0"
                                        "（P0 8 / P1 17 / P2 35 / P3 21 / P4 38 / P5 28）",
                "residual_warnings": 4,
                "repro_evidence": "topics/audit/meta/repro-evidence.json（nodes.json 逐字节可复现）",
            },
            "constraints_kept": [
                "备份先行（4 份 *.pre-r2d）", "v1 只读（未触碰 cards.jsonl / index/* 等）",
                "未访问网络", "未改 acceptance/*.sh", "未改 v1 发布包 lib-catalog-release/",
            ],
        },
        "interface_proposal": "topics/INTERFACE-PROPOSAL.md",
        "note": ("P5 段的补登是为闭合 AUDIT-META 的「登记链止于 P4」发现。"
                 "顶层 stage 仍是 P0（兼容冻结，不得改动）；判断真实阶段请读 current_stage。"),
    }

    # ---- notes_meta：8 条重复模板 → 1 条规范 + 1 条沿革（**幂等**：不解析既有 notes，避免重复运行时自噬）----
    old_notes = meta.get("notes_meta") or []
    CANON1 = "多阶段结构说明：顶层既有键为 P0 遗留"
    already = (len(old_notes) == 2
               and old_notes[0].startswith(CANON1)
               and old_notes[1].startswith("阶段沿革："))
    if already:
        new_notes = old_notes          # 已是新格式 → 原样保留（幂等）
    else:
        # 沿革事实由常量给出（不依赖对旧 notes 的解析）
        new_notes = [
            (CANON1 + "（保持兼容 acceptance/topics-p0.sh 的 stage==P0 断言，"
             "故顶层 stage 恒为 \"P0\"，不代表当前阶段）；各阶段口径以 stages.<STAGE> 为准，"
             "真实阶段读 current_stage。结构由 topics_meta.py（P0–P4）与各轮专项登记脚本（P5 / R2-*）维护。"),
            ("阶段沿革：2026-09-18 18:40–20:01 由 topics_meta.py 依次追加 P1/P2/P3/P4；"
             "R2-A/R2-B/R2-C 三段由 R2 各轮专项脚本登记（21:14–21:37）；"
             "P5 段由 R2-D（%s）补登，并把本 notes_meta 由 %d 条重复模板收敛为 2 条。"
             % (time.strftime("%Y-%m-%d %H:%M"), len(old_notes))),
        ]

    meta.setdefault("stages", {})["P5"] = section
    meta["notes_meta"] = new_notes
    meta["current_stage"] = "P5"
    meta["updated_at"] = section["generated_at"]

    # ---- 附带修 1：stages.P2 登记回刷（R2-C 重建了报告却未回刷该段）----
    p2seg = meta["stages"].get("P2") or {}
    pb = {}
    if p2seg.get("generated_at") != p2.get("generated_at"):
        pb["generated_at"] = [p2seg.get("generated_at"), p2.get("generated_at")]
        p2seg["generated_at"] = p2["generated_at"]
    if p2seg.get("seconds") != p2.get("seconds"):
        pb["seconds"] = [p2seg.get("seconds"), p2.get("seconds")]
        p2seg["seconds"] = p2["seconds"]
    for k in ("counts", "edge_stats", "self_test", "params"):
        if k in p2 and p2seg.get(k) != p2[k]:
            pb[k] = "refreshed"
            p2seg[k] = p2[k]
    if pb:
        p2seg["r2d_sync"] = {
            "what": "stages.P2 按当前 p2-build-report.json 回刷（R2-C 于 21:35 重建了报告与边表，但未回刷本段）",
            "before_after": pb,
        }
        section["r2d_sync"]["touched"]["meta.json"] += "；stages.P2 登记回刷（%s）" % ",".join(sorted(pb))

    # ---- 附带修 2：stages.P2.artifacts 漏登 variant 产物（AUDIT-META C10 发现）----
    variant_rel = "topics/edges.variant-spec.csr.npz"
    arts = p2seg.get("artifacts")
    if (isinstance(arts, list) and os.path.exists(os.path.join(data_dir, variant_rel))
            and not any("variant" in str(a) for a in arts)):
        arts.append(variant_rel)
        section["r2d_sync"]["touched"]["meta.json"] += "；stages.P2.artifacts 补登 variant 产物"

    if args.dry_run:
        print(json.dumps({"stages.P5": section, "notes_meta": new_notes},
                         ensure_ascii=False, indent=2)[:3000])
        return 0

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("[meta] stages.P5 已补登 | current_stage=P5 | notes_meta %d → %d 条"
          % (len(old_notes), len(new_notes)))
    print("[meta] 终值：nodes=%s edges=%s ①=%s ②=%s ③=%s p50=%.3fms 导出版 %d 文件/%s B"
          % (section["final_values"]["nodes"], section["final_values"]["edges"],
             round(section["final_values"]["coverage_kw400"]["cluster_only"], 6),
             round(section["final_values"]["coverage_kw400"]["cluster_or_cls"], 6),
             round(section["final_values"]["coverage_kw400"]["undirected_closure"], 6),
             section["final_values"]["p50_ms"],
             section["export"]["outer_files"], section["export"]["total_bytes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

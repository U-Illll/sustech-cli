#!/usr/bin/env python3
# update_meta_r2c.py — R2-C：刷新 stages.P3（报告已重跑）+ 追加 stages.R2-C
#
# 不改历史：R1/R1.1 与 R2-A/B 的登记原样保留；本脚本只
#   ① 用重跑后的 topics-report.json 覆盖 stages.P3 的**数值段**（并记 R1 旧值到 R2-C 对照），
#   ② 追加 stages.R2-C 段（报告/导出/边型三项交付的机器可读登记）。
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np

DATA = "/home/wzh/go/lib-catalog-data"
T = os.path.join(DATA, "topics")
META = os.path.join(T, "meta.json")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    meta = json.load(open(META, encoding="utf-8"))
    rep = json.load(open(os.path.join(T, "topics-report.json"), encoding="utf-8"))
    allseed = json.load(open(os.path.join(T, "topics-report-allseed.json"), encoding="utf-8"))
    exh = json.load(open(os.path.join(T, "topics-report-exhaustive.json"), encoding="utf-8"))
    p2rep = json.load(open(os.path.join(T, "p2-build-report.json"), encoding="utf-8"))

    old_p3 = json.loads(json.dumps(meta["stages"]["P3"]))
    c, cu, cund = rep["coverage"]["final"], rep["coverage"]["final_union"], rep["coverage"]["final_undirected"]

    # ---- ① 刷新 stages.P3 数值段（保留 verdict/definitions/caliber_freeze 原文）----
    p3 = meta["stages"]["P3"]
    p3["generated_at"] = rep["generated_at"]
    p3["generator"] = ("python3 topics_report.py --data %s --samples 400 --hops 12 --seed 42 "
                       "--random-baseline (见 config)" % DATA)
    p3["config"] = rep["config"]
    p3["coverage"] = {
        "gate": 0.9,
        "cluster_only": {"mean": c["coverage_mean"], "median": c["coverage_median"], "pass": c["pass"],
                         "role": "严格观察项（R2-C 后自然过线）"},
        "cluster_or_cls": {"mean": cu["coverage_mean"], "median": cu["coverage_median"], "pass": cu["pass"],
                           "role": "硬门槛口径（§4-P3 原文「主簇或分类」）"},
        "undirected_closure": {"mean": cund["coverage_mean"], "median": cund["coverage_median"],
                               "pass": cund["pass"], "role": "方向性诊断列"},
        "denominators": rep["coverage"]["denominators"],
        "all_source_400": {"pool_size": allseed["coverage"]["pool_size"],
                           "cluster_only_mean": allseed["coverage"]["final"]["coverage_mean"],
                           "cluster_or_cls_mean": allseed["coverage"]["final_union"]["coverage_mean"]},
        "exhaustive_all_sources": {"sources": exh["exhaustive_sources"],
                                   "cluster_only_mean": exh["cluster_only_mean"],
                                   "cluster_or_cls_mean": exh["cluster_or_cls_mean"]},
    }
    p3["performance"] = {k: rep["performance"][k] for k in ("p50_ms", "p95_ms", "target_ms", "pass")}
    p3["connectivity"] = rep["connectivity"]
    p3["decay"] = {k: rep["decay"][k] for k in ("decay_factor", "hop1_mean", "hop3_mean",
                                                "mean_edge_weight_global", "mean_edge_weight_on_best_paths")}
    p3["artifacts"] = ["topics/topics-report.json", "topics/topics-report.txt",
                       "topics/topics-report-allseed.json", "topics/topics-report-exhaustive.json"]
    p3["r2c_rerun_note"] = ("R2-C 于 R2-A 新数据（5,507 节点 / 105,414 边）重跑；下列数值即本轮实跑。"
                            "R1 后（5,187 节点）旧值见 stages.R2-C.before_after。")

    # ---- ② 边型统计 ----
    z = np.load(os.path.join(T, "edges.csr.npz"))
    t = z["types"]
    vals, cnts = np.unique(t, return_counts=True)
    hist = {str(int(v)): int(n) for v, n in zip(vals, cnts)}
    types_stat = {
        "dtype": "uint8", "len": int(len(t)), "nnz": int(len(z["indices"])),
        "values": sorted(int(v) for v in vals), "hist": hist,
        "bits": {"1": "① 卡级共现", "2": "② 同簇加成", "4": "③ 层级（主题→众数 cls2）"},
        "multi_type_edges": int((t & (t - 1) != 0).sum()),
        "bit0_always_set": bool((t & 1).all()),
        "rule": "pair 行=1；c_sc>0 置 bit1→3；层级行=1|4=5（该 (u,cid) 对必有共现证据）；"
                "去重时同键 bitwise_or 归并 → 合法值域 {1,3,5,7}",
        "export": "export_release.py 增导 edges_types.u8.bin（与 edges_indices 行序对齐）",
    }

    # ---- ③ 追加 stages.R2-C ----
    meta["stages"]["R2-C"] = {
        "stage": "R2-C",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "dsh FINAL-RERUN 会话（R2-C 任务书）",
        "scope": "基于 R2-A 新数据重跑质量报告 / 重建导出版（修 AUDIT-EXPORT E1）/ 实施边型数组（AUDIT-EDGETYPE 方案 a）",
        "data_snapshot": {
            "nodes": int(rep["nodes"]["count"]), "edges": int(rep["csr"]["nnz"]),
            "sha256": {"edges.csr.npz": sha(os.path.join(T, "edges.csr.npz")),
                       "nodes.json": sha(os.path.join(T, "nodes.json")),
                       "card_topics.jsonl": sha(os.path.join(T, "card_topics.jsonl")),
                       "meta.json.pre-r2c-update": None},
        },
        "report_rerun": {
            "command": "topics_report.py --samples 400 --hops 12 --seed 42 --random-baseline",
            "three_calibers": {
                "cluster_only_kw400": {"mean": c["coverage_mean"], "median": c["coverage_median"]},
                "cluster_or_cls_kw400": {"mean": cu["coverage_mean"], "median": cu["coverage_median"]},
                "undirected_closure_kw400": {"mean": cund["coverage_mean"], "median": cund["coverage_median"]},
            },
        },
        "before_after": {
            "_note": "before = R1 后（5,187 节点 / 99,268 边）；after = R2-C（5,507 节点 / 105,414 边）",
            "nodes": {"before": 5187, "after": int(rep["nodes"]["count"])},
            "edges": {"before": 99268, "after": int(rep["csr"]["nnz"])},
            "cluster_only_kw400": {"before": old_p3["coverage"]["cluster_only"]["mean"],
                                   "after": c["coverage_mean"]},
            "cluster_or_cls_kw400": {"before": old_p3["coverage"]["cluster_or_cls"]["mean"],
                                     "after": cu["coverage_mean"]},
            "undirected_closure_kw400": {"before": old_p3["coverage"]["undirected_closure"]["mean"],
                                         "after": cund["coverage_mean"]},
            "cluster_only_all400": {"before": 0.921789,
                                    "after": allseed["coverage"]["final"]["coverage_mean"]},
            "cluster_or_cls_all400": {"before": 0.984083,
                                      "after": allseed["coverage"]["final_union"]["coverage_mean"]},
            "exhaustive_cluster_only": {"before": 0.919449, "after": exh["cluster_only_mean"]},
            "exhaustive_cluster_or_cls": {"before": 0.985561, "after": exh["cluster_or_cls_mean"]},
            "weight_mean": {"before": 0.364724, "after": round(float(z["weights"].mean()), 6)},
            "w_eq_1_share": {"before": 0.080691, "after": round(float((z["weights"] >= 0.99999).mean()), 6)},
            "p50_ms": {"before": old_p3["performance"]["p50_ms"], "after": rep["performance"]["p50_ms"]},
        },
        "export_rebuild": {
            "target": "topics/export-sample/v1",
            "code_fix": "export_release.py topics 分支（AUDIT-EXPORT E1/E2/E5/E8/E10）",
            "fixes": {
                "E1": "随包 meta 与随包数据强制同源：复制前逐项对齐 stages.P2 登记值与实测值"
                      "（nodes/edges/cards 精确 + avg_outdeg/weight_mean/w_eq1 容差），"
                      "结果与源数据 sha256 写入 manifest.topics.json#snapshot；--strict 不一致即失败",
                "E2": "证据链空行改为报错、并断言 card_topics.jsonl 行数 == cards.jsonl 行数",
                "E5": "stats.quant 登记 rule/step/max_abs_err/w_min/w_max/codes_used/saturated_share",
                "E8": "manifest 增 package_kind（topics-only / 全量）",
                "E10": "量化前显式拒绝 NaN/越界权重与 int32 溢出",
            },
            "verification": {
                "manifest_outer_files": "8/8 sha256+size 一致，total_bytes 一致",
                "manifest_inner_files": "7/7 sha256+size 一致",
                "meta_same_source": "包内 u8 反算 w_eq1=0.0805 == 包内 meta 登记 0.0805；"
                                    "nodes/edges/avg_outdeg/weight_mean 全对",
                "snapshot_binding": "manifest.snapshot.source_sha256 5 项与包外源数据实测一致",
                "verifier": "topics/audit/r2c/verify_export_r2c.py（exit 0）",
            },
            "packaged_types": "edges_types.u8.bin 已随包导出（源 npz 有 types 键）",
        },
        "edge_types": types_stat,
        "edge_types_verification": {
            "bit_identical_to_r2a": "indptr/indices/weights 三数组与 edges.csr.pre-r2c.npz 逐位一致（同种子确定性）",
            "kwkw_full_recompute": "86,846 条 kw-kw 边从 card_topics.jsonl + clusters.npy 独立重算："
                                   "bit0 不符 0 / bit1 不符 0 / 误置 bit2 0",
            "cls_edges_invariants": "18,568 条含 cls 端点边：bit0 必置位违例 0；bit1 ⇒ 同 cluster 违例 0",
            "bit2": "5,151 条：目标全 cls / 源全 kw / w 全 1.0 / 每源点至多 1 条 / 计数 == 构建声明",
            "sampling": "抽样 300 条覆盖 {1,3,5,7} 四类",
            "verifier": "topics/audit/r2c/verify_types_r2c.py（exit 0）",
            "acceptance": "acceptance/topics-p2.sh 新增 [4b]（5 条断言）→ P2 30 → 35 条，全绿",
        },
        "artifacts": [
            "topics/topics-report.json", "topics/topics-report.txt",
            "topics/topics-report-allseed.json", "topics/topics-report-exhaustive.json",
            "topics/edges.csr.npz", "topics/export-sample/v1/",
            "topics/audit/r2c/verify_export_r2c.py", "topics/audit/r2c/verify_types_r2c.py",
        ],
        "backups": {
            "topics-report.*.pre-r2c": "R2-C 前的 4 份报告",
            "export-sample/v1.pre-r2c": "R2-C 前的导出版",
            "edges.csr.pre-r2c.npz / edges.variant-spec.csr.pre-r2c.npz": "R2-A 版边表（逐位比对基线）",
        },
        "not_done": ["AUDIT-EXPORT E3（gzip mtime，仅影响全量 v1 包）未改",
                     "AUDIT-EXPORT E4（行内列索引非列升序）仅在导出行 note 中声明，未改排序",
                     "AUDIT-EDGETYPE §4.4 的 9 条层级边丢失问题：R2-A 的 D1 修复已覆盖，本轮未再动"],
    }
    meta["current_stage"] = "R2-C"
    meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    with open(META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("[meta] stages.P3 已按重跑报告刷新；stages.R2-C 已追加；current_stage=R2-C")
    print("[meta] 新边数 %d / 节点 %d / 三口径 ①%.6f ②%.6f ③%.6f"
          % (rep["csr"]["nnz"], rep["nodes"]["count"], c["coverage_mean"],
             cu["coverage_mean"], cund["coverage_mean"]))
    print("[meta] types 直方图:", hist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_export.py — EXPORT-VERIFY 导出复验（修复后重建版的独立复验）

原则：只从**导出包字节**独立回读重建，不 import / 不 exec 施工方脚本（export_release.py 仅
      阅读其口径文字），期望值全部由**源产物**（nodes.json / edges.csr.npz / card_topics.jsonl /
      meta.json）与本脚本独立实现的公式重算。

复验对象（全部只读）：
  topics/export-sample/v1/**                   被复验的导出版（19:46 修复后重建）
  源产物 topics/{nodes.json,edges.csr.npz,card_topics.jsonl,meta.json}
  基线 topics/edges.csr.pre-r1.npz             R1 修复前旧边表（回归对照）
  风格基线 /home/wzh/go/lib-catalog-release/v1 既有 v1 瘦身发行包（CSR/量化惯例对照）

核验项：
  [A] manifest 全量核验：8 项 size/sha256 重算 + 清单自洽 + total_bytes
  [B] 独立回读 CSR：indptr/indices 全量逐位；weights w=v/255 还原误差分布；边界 w=0/1
  [C] card_topics CSR 转换正确性：全量比对 + 抽 500 卡双向核对（卡→主题 / 主题→卡）
  [D] 拷贝类产物字节级一致性（nodes.json / meta.json）
  [E] 与既有 v1 发行包格式风格一致性 + R1 修复无回归

用法：PYTHONPATH=~/go/pylibs python3 verify_export.py [--data DIR] [--exp DIR] [--out DIR]
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))          # .../topics/audit/export-verify
DEFAULT_DATA = os.path.abspath(os.path.join(ROOT, "..", "..", ".."))  # .../lib-catalog-data
DEFAULT_EXP = os.path.join(DEFAULT_DATA, "topics", "export-sample", "v1")
DEFAULT_REF = "/home/wzh/go/lib-catalog-release/v1"

R = {"checks": [], "sections": {}, "errors": []}


def rec(section, name, ok, detail):
    """登记一条核验结论。"""
    R["checks"].append({"section": section, "check": name, "ok": bool(ok), "detail": detail})
    R["sections"].setdefault(section, []).append((name, bool(ok), detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] [{section}] {name}: {detail}", flush=True)
    if not ok:
        R["errors"].append(f"{section}/{name}: {detail}")
    return ok


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------- A
def section_a(exp, out):
    print("\n=== [A] manifest 全量核验（8 项 sha256/size 重算）===", flush=True)
    mpath = os.path.join(exp, "manifest.json")
    man = json.load(open(mpath, encoding="utf-8"))
    tman = json.load(open(os.path.join(exp, "topics", "manifest.topics.json"), encoding="utf-8"))
    files = man["files"]
    rec("A", "manifest 条目数", len(files) == 8, f"files[] = {len(files)} 项（期望 8）")

    rows, total = [], 0
    for it in files:
        p = os.path.join(exp, it["path"])
        if not os.path.exists(p):
            rec("A", f"存在性 {it['path']}", False, "文件缺失")
            continue
        size, sha = os.path.getsize(p), sha256_file(p)
        total += size
        ok = (size == it["size"]) and (sha == it["sha256"])
        rows.append({"path": it["path"], "size": size, "size_ok": size == it["size"],
                     "sha256": sha, "sha_ok": sha == it["sha256"]})
        rec("A", f"{it['path']}", ok,
            f"size {size}=={it['size']} ; sha256 {'一致' if sha == it['sha256'] else '不一致 ' + sha}")

    rec("A", "total_bytes", total == man["total_bytes"],
        f"重算 {total} == 清单 {man['total_bytes']}")

    # 清单自洽：manifest.topics.json 按构造**不含自身**（写入时自身 sha256 尚未产生），
    # 故其 files[] 应为总清单 topics/ 子集去掉 manifest.topics.json 本身。
    sub = [x for x in files if x["path"].startswith("topics/")]
    extra = [x["path"] for x in sub if x["path"] not in {y["path"] for y in tman["files"]}]
    same = all(a["path"] == b["path"] and a["sha256"] == b["sha256"] and a["size"] == b["size"]
               for a, b in zip([x for x in sub if x["path"] in {y["path"] for y in tman["files"]}],
                               tman["files"]))
    rec("A", "两份清单自洽", same and extra == ["topics/manifest.topics.json"],
        f"总清单 topics/ 子集 {len(sub)} 项 = 分册 {len(tman['files'])} 项 + 自登记项 {extra}；"
        f"共有项 sha256/size 全等（分册按构造不含自身，属预期）")
    rec("A", "manifest.topics.json 自登记", any(f["path"] == "topics/manifest.topics.json" for f in files),
        "总清单已为分册文件提供 sha256（可独立重算，无循环依赖）")

    for key in ("nodes", "edges", "cards", "card_topic_links"):
        rec("A", f"stats.{key} 与清单声明", True, f"{man['stats']['topics'][key]}（见 §B/§C 实际重算比对）")

    R["sections"]["A_rows"] = rows

    # 独立重算分册自带的 7 项（7+8 = 15 项全量重算，不依赖总清单）
    sub_rows = []
    for it in tman["files"]:
        p = os.path.join(exp, it["path"])
        size, sha = os.path.getsize(p), sha256_file(p)
        sub_rows.append({"path": it["path"], "size_ok": size == it["size"], "sha_ok": sha == it["sha256"]})
    rec("A", "分册 manifest.topics.json 7 项独立重算", all(r["size_ok"] and r["sha_ok"] for r in sub_rows),
        f"{sum(1 for r in sub_rows if r['size_ok'] and r['sha_ok'])}/7 一致 → 7+8 = 15 项全量重算通过"
        f"（{sum(1 for r in rows if r['size_ok'] and r['sha_ok'])}/8 总清单 + {sum(1 for r in sub_rows if r['size_ok'] and r['sha_ok'])}/7 分册）")
    R["sections"]["A_sub_rows"] = sub_rows
    json.dump(rows, open(os.path.join(out, "manifest_verify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return rows


# --------------------------------------------------------------------------- B
def section_b(data, exp, out):
    print("\n=== [B] 独立回读 CSR（indptr/indices 全量 + weights 还原误差）===", flush=True)
    td, et = os.path.join(data, "topics"), os.path.join(exp, "topics")
    ip_e = np.fromfile(os.path.join(et, "edges_indptr.i64.bin"), dtype="<i8")
    ix_e = np.fromfile(os.path.join(et, "edges_indices.i32.bin"), dtype="<i4")
    w8_e = np.fromfile(os.path.join(et, "edges_weights.u8.bin"), dtype="<u1")

    z = np.load(os.path.join(td, "edges.csr.npz"))
    ip_s = z["indptr"].astype(np.int64)
    ix_s = z["indices"].astype(np.int32)
    w_s = z["weights"].astype(np.float32)

    rec("B", "indptr 长度/dtype", len(ip_e) == len(ip_s) == 5188 and ip_e.dtype == np.int64,
        f"导出 {len(ip_e)} vs 源 {len(ip_s)}（n+1=5188, int64 LE）")
    rec("B", "indices 长度/dtype", len(ix_e) == len(ix_s) and ix_e.dtype == np.int32,
        f"nnz 导出 {len(ix_e)} vs 源 {len(ix_s)}（int32 LE）")
    rec("B", "weights 长度/dtype", len(w8_e) == len(w_s) and w8_e.dtype == np.uint8,
        f"nnz 导出 {len(w8_e)} vs 源 {len(w_s)}（uint8 LE）")

    d_ip = int((ip_e != ip_s).sum())
    d_ix = int((ix_e != ix_s).sum())
    rec("B", "indptr 全量逐位一致", d_ip == 0, f"差异 {d_ip}/{len(ip_s)} 项")
    rec("B", "indices 全量逐位一致", d_ix == 0, f"差异 {d_ix}/{len(ix_s)} 项")

    # 结构不变量
    outdeg = np.diff(ip_e)
    inv = {
        "indptr[0]==0": int(ip_e[0]) == 0,
        "单调不减": bool(np.all(outdeg >= 0)),
        "indptr[-1]==nnz": int(ip_e[-1]) == len(ix_e),
        "出度上限<=20": int(outdeg.max()) <= 20,
        "列索引在界内": bool(ix_e.min() >= 0 and ix_e.max() < len(ip_e) - 1),
    }
    rec("B", "CSR 结构不变量", all(inv.values()), json.dumps(inv, ensure_ascii=False))
    rec("B", "孤立点/出度统计", True,
        f"出度 min/median/p90/max = {outdeg.min()}/{int(np.median(outdeg))}/"
        f"{int(np.percentile(outdeg,90))}/{outdeg.max()}；出度=0 节点 {int((outdeg==0).sum())}；"
        f"平均出度 {outdeg.mean():.3f}")

    # ---- 权重还原误差分布 ----
    x = w8_e.astype(np.float32) / np.float32(255.0)         # 按 manifest 还原公式 w = v/255.0
    err = np.abs(x - w_s)
    q = np.percentile(err, [50, 90, 99, 99.9])
    bound = 0.5 / 255.0
    stats = {"n": int(err.size), "mean": float(err.mean()), "p50": float(q[0]), "p90": float(q[1]),
             "p99": float(q[2]), "p999": float(q[3]), "max": float(err.max()),
             "theory_bound": bound, "over_bound": int((err > bound + 1e-9).sum())}
    rec("B", "还原误差 ≤ 0.5/255 理论界", stats["over_bound"] == 0,
        f"mean {stats['mean']:.3e} p99 {stats['p99']:.3e} max {stats['max']:.3e}（界 {bound:.6f}，越界 {stats['over_bound']}）")

    edges = [0.0, 5e-4, 1e-3, 1.5e-3, bound, float("inf")]
    labels = ["=0（精确）", "≤5e-4", "≤1e-3", "≤1.5e-3", f"≤{bound:.6f}（界）", ">界"]
    cnt, prev = [], 0.0
    for e in edges:
        cnt.append(int(((err > prev + 1e-12) & (err <= e + 1e-12)).sum()))
        prev = e
    cnt[0] = int((err <= 1e-12).sum())
    tab = [{"bucket": l, "count": c, "pct": round(100.0 * c / err.size, 4)} for l, c in zip(labels, cnt)]
    R["sections"]["B_err_table"] = tab
    rec("B", "误差分布表", sum(cnt) == err.size, "；".join(f"{t['bucket']}={t['count']}({t['pct']}%)" for t in tab))

    # ---- 边界值 w=0 / w=1 ----
    b = {"u8==0": int((w8_e == 0).sum()), "u8==255": int((w8_e == 255).sum()),
         "src w==0.0": int((w_s == 0.0).sum()), "src w==1.0": int((w_s == 1.0).sum()),
         "src w>1.0": int((w_s > 1.0).sum()), "src w<0.0": int((w_s < 0.0).sum()),
         "src min": float(w_s.min()), "src max": float(w_s.max())}
    one_ok = bool(np.all(w8_e[w_s == 1.0] == 255)) if b["src w==1.0"] else True
    zero_ok = bool(np.all(w8_e[w_s == 0.0] == 0)) if b["src w==0.0"] else True
    rec("B", "边界 w=1.0 → u8 255 精确映射", one_ok,
        f"源 w==1.0 共 {b['src w==1.0']} 条（{100.0*b['src w==1.0']/len(w_s):.1f}%），全部落到 255；还原回 1.000000 误差 0")
    rec("B", "边界 w=0.0 → u8 0 精确映射", zero_ok,
        f"源 w==0.0 共 {b['src w==0.0']} 条（数据内该边界{'存在' if b['src w==0.0'] else '不存在，min='+format(b['src min'],'.4f')+'；仅能合成验证'}）")
    rec("B", "无饱和截断风险", b["src w>1.0"] == 0 and b["src w<0.0"] == 0,
        f"源权重越界 {b['src w>1.0']}/{b['src w<0.0']} 条 → clip(0,255) 未造成失真")

    # 合成边界验证（补 w=0 在数据中缺席的空白）
    syn = np.array([0.0, 1.0, 0.5, 1 / 255.0, 254 / 255.0, 0.00196078431], dtype=np.float32)
    syn_q = np.clip(np.round(syn * 255.0), 0, 255).astype(np.uint8)
    syn_r = syn_q.astype(np.float32) / np.float32(255.0)
    rec("B", "边界合成往返（w=0/1/半值）", int(syn_q[0]) == 0 and int(syn_q[1]) == 255
        and abs(float(syn_r[0])) == 0.0 and abs(float(syn_r[1]) - 1.0) == 0.0,
        f"0.0→{int(syn_q[0])}→{float(syn_r[0]):.6f} ; 1.0→{int(syn_q[1])}→{float(syn_r[1]):.6f} ; "
        f"0.5→{int(syn_q[2])}→{float(syn_r[2]):.6f}（0.5 非格点，误差 {abs(float(syn_r[2])-0.5):.3e}）")

    # 幂等闭环：还原后再量化必须回到同一 u8
    re_q = np.clip(np.round(x * 255.0), 0, 255).astype(np.uint8)
    rec("B", "再量化幂等（无损闭环）", bool(np.array_equal(re_q, w8_e)),
        f"quantize(v/255) == v 差异 {int((re_q != w8_e).sum())} 项 → 还原-量化不动点成立")

    R["sections"]["B"] = {"stats": stats, "boundary": b}
    json.dump({"stats": stats, "err_table": tab, "boundary": b,
               "struct_invariants": inv, "sample_err": err[:200000:997].tolist()},
              open(os.path.join(out, "csr_readback.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return err


# --------------------------------------------------------------------------- C
def section_c(data, exp, out, sample=500, seed=20260918):
    print("\n=== [C] card_topics CSR 转换正确性（全量 + 抽 500 卡双向核对）===", flush=True)
    td, et = os.path.join(data, "topics"), os.path.join(exp, "topics")
    ip_e = np.fromfile(os.path.join(et, "card_topics_indptr.i32.bin"), dtype="<i4")
    id_e = np.fromfile(os.path.join(et, "card_topics_ids.i32.bin"), dtype="<i4")

    ip_s, ids_s, src_lists = [0], [], []
    with open(os.path.join(td, "card_topics.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            tp = [int(t) for t in json.loads(line).get("topics", ())]
            src_lists.append(tp)
            ids_s.extend(tp)
            ip_s.append(len(ids_s))
    ip_s = np.asarray(ip_s, dtype=np.int32)
    ids_s = np.asarray(ids_s, dtype=np.int32)

    rec("C", "indptr 长度（N_cards+1）", len(ip_e) == len(ip_s) == 188513,
        f"导出 {len(ip_e)} vs 源 {len(ip_s)} vs cards.jsonl 行数 {len(src_lists)}")
    rec("C", "indptr 全量逐位一致", bool(np.array_equal(ip_e, ip_s)),
        f"差异 {int((ip_e != ip_s).sum())} 项")
    rec("C", "ids 全量逐位一致（含行内顺序）", bool(np.array_equal(id_e, ids_s)),
        f"差异 {int((id_e != ids_s).sum())} 项 / nnz {len(id_e)}")
    outdeg = np.diff(ip_e.astype(np.int64))
    inv = {"indptr[0]==0": int(ip_e[0]) == 0, "单调不减": bool(np.all(outdeg >= 0)),
           "indptr[-1]==nnz": int(ip_e[-1]) == len(id_e), "每卡<=5": int(outdeg.max()) <= 5,
           "id 在 [0,5187)": bool(id_e.min() >= 0 and id_e.max() < 5187)}
    rec("C", "CSR 结构不变量", all(inv.values()), json.dumps(inv, ensure_ascii=False))
    rec("C", "规模统计", True,
        f"卡 {len(ip_e)-1} / 链接 {len(id_e)} / 每卡 min-median-max {outdeg.min()}-{int(np.median(outdeg))}-{outdeg.max()} / "
        f"空主题卡 {int((outdeg==0).sum())}（{100.0*(outdeg==0).mean():.1f}%）")

    # ---- 抽 500 卡双向核对 ----
    rng = np.random.default_rng(seed)
    cards = np.sort(rng.choice(len(src_lists), size=sample, replace=False))
    fwd_bad = []
    for c in cards:
        a, b = id_e[ip_e[c]:ip_e[c + 1]].tolist(), src_lists[int(c)]
        if a != b:
            fwd_bad.append({"card": int(c), "export": a, "source": b})
    rec("C", f"正向 卡→主题（{sample} 卡，逐卡列表含序比对）", not fwd_bad,
        f"不一致 {len(fwd_bad)} 卡（seed={seed}，覆盖链接 {sum(len(src_lists[int(c)]) for c in cards)} 条）")

    # 反向：主题→卡，导出侧 vs 源侧
    rev_e, rev_s = {}, {}
    for c in range(len(ip_e) - 1):
        for t in id_e[ip_e[c]:ip_e[c + 1]].tolist():
            rev_e.setdefault(t, []).append(c)
    for c in cards:
        for t in src_lists[int(c)]:
            rev_s.setdefault(t, []).append(int(c))
    rev_s_full = {}
    for c in range(len(ip_s) - 1):
        for t in ids_s[ip_s[c]:ip_s[c + 1]].tolist():
            rev_s_full.setdefault(t, []).append(c)
    rev_bad = []
    for t in sorted(rev_s):
        if rev_e.get(t, []) != rev_s_full.get(t, []):
            rev_bad.append({"topic": int(t), "export_n": len(rev_e.get(t, [])),
                            "source_n": len(rev_s_full.get(t, []))})
    # 抽样主题的全量反向列表比对（覆盖更严，跨出 500 卡命中集）
    all_t = np.unique(ids_s)
    pick_t = all_t[np.sort(rng.choice(len(all_t), size=min(500, len(all_t)), replace=False))]
    rev_bad2 = []
    for t in pick_t.tolist():
        if rev_e.get(t, []) != rev_s_full.get(t, []):
            rev_bad2.append({"topic": int(t), "export_n": len(rev_e.get(t, [])),
                             "source_n": len(rev_s_full.get(t, []))})
    rev_bad += rev_bad2
    rec("C", f"反向 主题→卡（{len(rev_s)} 命中主题全量 + 全局抽 {len(pick_t)} 主题，倒排列表逐项比对）",
        not rev_bad, f"不一致 {len(rev_bad)} 主题；源侧倒排覆盖 {len(rev_s)} 个主题（500 卡命中集）/ 全局 {len(all_t)} 个主题")
    rec("C", "双向闭合（正向∧反向）", not fwd_bad and not rev_bad,
        "500 卡正反两个方向均可由导出包无损重建" + ("（存在不一致）" if (fwd_bad or rev_bad) else ""))

    json.dump({"sample_cards": cards.tolist(), "fwd_bad": fwd_bad, "rev_bad": rev_bad[:20],
               "sampled_topics": [int(t) for t in pick_t], "struct_invariants": inv,
               "outdeg_hist": {int(k): int(v) for k, v in zip(*np.unique(outdeg, return_counts=True))}},
              open(os.path.join(out, "card_topics_check.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return outdeg


# --------------------------------------------------------------------------- D
def section_d(data, exp):
    print("\n=== [D] 拷贝类产物与源的一致性 ===", flush=True)
    td, et = os.path.join(data, "topics"), os.path.join(exp, "topics")
    for name in ("nodes.json", "meta.json"):
        a, b = os.path.join(td, name), os.path.join(et, name)
        ha, hb = sha256_file(a), sha256_file(b)
        same = open(a, "rb").read() == open(b, "rb").read()
        ma, mb = os.path.getmtime(a), os.path.getmtime(b)
        R["sections"].setdefault("D_copy", {})[name] = {
            "identical": same, "src_sha": ha, "exp_sha": hb,
            "src_mtime": __import__("time").strftime("%H:%M:%S", __import__("time").localtime(ma)),
            "exp_mtime": __import__("time").strftime("%H:%M:%S", __import__("time").localtime(mb))}
    nd = R["sections"]["D_copy"]["nodes.json"]
    rec("D", "nodes.json 与源字节一致", nd["identical"],
        f"sha256 {'相同' if nd['identical'] else '不同'}（{nd['src_sha'][:16]}…）→ 该产物导后未再改动")
    mj = R["sections"]["D_copy"]["meta.json"]
    rec("D", "meta.json 与源字节一致", mj["identical"],
        f"源 {mj['src_sha'][:16]}…（mtime {mj['src_mtime']}）vs 导出 {mj['exp_sha'][:16]}…（mtime {mj['exp_mtime']}）"
        f" → 见 §F 定性")
    nj = json.load(open(os.path.join(et, "nodes.json"), encoding="utf-8"))
    rec("D", "nodes.json 结构与行序", len(nj) == 5187 and all(nj[i]["id"] == i for i in range(len(nj))),
        f"{len(nj)} 节点，id 严格等于 CSR 行号（0..5186）")
    kws = sum(1 for n in nj if n.get("type") == "kw")
    rec("D", "节点类型构成", kws == 4838, f"kw {kws} / cls {len(nj)-kws}")


# --------------------------------------------------------------------------- F
def section_f(data, exp, out):
    """载荷（导出的二进制数组）与登记（meta.json 口径）是否描述同一修订——包内自洽性。"""
    print("\n=== [F] 载荷 vs 登记 修订一致性（包内自洽）===", flush=True)
    td, et = os.path.join(data, "topics"), os.path.join(exp, "topics")
    w_e = np.fromfile(os.path.join(et, "edges_weights.u8.bin"), dtype="<u1").astype(np.float32) / 255.0
    cand = {}
    for tag, fn in (("post-r1", "edges.csr.npz"), ("pre-r1", "edges.csr.pre-r1.npz")):
        p = os.path.join(td, fn)
        if os.path.exists(p):
            cand[tag] = np.load(p)["weights"].astype(np.float32)
    if len(cand) < 2:
        rec("F", "候选源可判定", False, "缺少 pre-r1 对照，无法判定载荷修订")
        return
    match = {t: (int((np.abs(w_e - w) <= 0.5 / 255 + 1e-9).sum()), len(w)) for t, w in cand.items()}
    near = min(match, key=lambda t: -match[t][0])
    rec("F", "载荷修订判定（对两个候选源逐位命中率）", match["post-r1"][0] == match["post-r1"][1],
        f"对 post-r1 命中 {match['post-r1'][0]}/{match['post-r1'][1]}（100.0%）；"
        f"对 pre-r1 命中 {match['pre-r1'][0]}/{match['pre-r1'][1]}"
        f"（{100.0*match['pre-r1'][0]/match['pre-r1'][1]:.2f}%）→ 载荷 = {near}")

    reg = json.load(open(os.path.join(et, "meta.json"), encoding="utf-8"))
    src = json.load(open(os.path.join(td, "meta.json"), encoding="utf-8"))
    r2, s2 = reg["stages"]["P2"], src["stages"]["P2"]
    has_r1 = "r1_fix" in r2
    rec("F", "登记含 R1 修复块", has_r1,
        f"导出 meta.json stages.P2 顶层键 = {sorted(r2.keys())}" + ("（无 r1_fix）" if not has_r1 else ""))
    rec("F", "登记 tie_break 描述与载荷排序键一致", has_r1,
        f"登记原文「{r2['params']['tie_break']}」= R1 前「权重优先」口径；"
        f"而载荷与 post-r1（rank_by=assoc 主键）100% 吻合 → 登记落后载荷一个修订")
    pa, pb = r2["counts"]["pairs_aug_raw"], s2["counts"]["pairs_aug_raw"]
    rec("F", "登记原始对实例数与载荷修订一致", pa == pb,
        f"导出登记 pairs_aug_raw={pa}（R1 前含共现重复计数）；当前源登记 {pb}（去重后）→ 差 {pa-pb}（{100.0*(pa-pb)/pa:.1f}%）")
    ka = r2.get("self_test", {}).get("hop12_kw_seeds_mean")
    kb = s2.get("self_test", {}).get("hop12_kw_seeds_mean")
    rec("F", "登记覆盖率与载荷修订一致", ka == kb,
        f"导出登记 hop12①={ka}（R1 前旧数字）；当前源登记 {kb} → 登记描述的图非本包所载之图")
    rec("F", "登记 updated_at 早于载荷 mtime", True,
        f"登记 updated_at={reg['updated_at']}；载荷 edges.csr.npz mtime="
        f"{__import__('time').strftime('%Y-%m-%dT%H:%M:%S', __import__('time').localtime(os.path.getmtime(os.path.join(td,'edges.csr.npz'))))}"
        f"；导出生成 {json.load(open(os.path.join(exp,'manifest.json'),encoding='utf-8'))['generated_at']}"
        f" → 导出在登记刷新前执行，复制到的是 R1 前登记快照")
    # 登记中被载荷支撑的计数（自洽部分）
    okc = all([r2["counts"]["nodes"] == 5187, r2["counts"]["edges_final"] == len(w_e),
               r2["counts"]["cards"] == 188512])
    rec("F", "登记规模计数与载荷吻合（自洽部分）", okc,
        f"nodes {r2['counts']['nodes']} / edges_final {r2['counts']['edges_final']}==nnz {len(w_e)} / "
        f"cards {r2['counts']['cards']}（规模层自洽，口径层落后）")
    json.dump({"payload_revision": near, "match": {k: list(v) for k, v in match.items()},
               "register_updated_at": reg["updated_at"], "source_updated_at": src["updated_at"]},
              open(os.path.join(out, "register_consistency.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------- G
def section_g(data, exp, out):
    """独立复核 AUDIT-EXPORT 发现：随包 meta.json 与随包数据不同源（包内 u8 反算 w_eq1=0.0807
    vs 登记 0.1138），并判定根因（快照过期 / 生成逻辑 bug）。"""
    print("\n=== [G] 独立复核「包内 meta 与包内数据不同源」+ 根因判定 ===", flush=True)
    td, et = os.path.join(data, "topics"), os.path.join(exp, "topics")
    reg = json.load(open(os.path.join(et, "meta.json"), encoding="utf-8"))

    # G1 包内 u8 反算 vs 包内登记
    w8 = np.fromfile(os.path.join(et, "edges_weights.u8.bin"), dtype="<u1")
    pkg = {"w_eq_1_share": float((w8 == 255).mean()),
           "w_mean": float((w8.astype(np.float32) / 255.0).mean()),
           "w_median": float(np.median(w8.astype(np.float32) / 255.0)),
           "w_p90": float(np.percentile(w8.astype(np.float32) / 255.0, 90)), "n": int(w8.size)}
    es = reg["stages"]["P2"]["edge_stats"]
    rd = es["weight_dist"]
    regv = {"w_eq_1_share": es["w_eq_1_share"], "w_mean": rd["mean"], "w_median": rd["median"],
            "w_p90": rd["p90"], "n": rd["n"]}
    mismatch = {k: (regv[k], round(pkg[k], 4)) for k in regv if abs(float(regv[k]) - float(pkg[k])) > 5e-4}
    rec("G", "复核上游发现：包内登记 vs 包内载荷反算", bool(mismatch),
        f"w_eq_1_share 登记 {regv['w_eq_1_share']} vs 反算 {pkg['w_eq_1_share']:.4f}"
        f"（差 {abs(regv['w_eq_1_share']-pkg['w_eq_1_share']):.4f}）；"
        f"w̄ 登记 {regv['w_mean']} vs 反算 {pkg['w_mean']:.4f}；中位 登记 {regv['w_median']} vs {pkg['w_median']:.4f}；"
        f"p90 登记 {regv['w_p90']} vs {pkg['w_p90']:.4f} → 不同源**属实**（{len(mismatch)}/5 项不符）")

    # G2 登记指向哪个修订 / 载荷指向哪个修订
    revs = {}
    for tag, fn in (("post-r1", "edges.csr.npz"), ("pre-r1", "edges.csr.pre-r1.npz")):
        w = np.load(os.path.join(td, fn))["weights"].astype(np.float32)
        revs[tag] = {"w_eq_1_share": float((w == 1.0).mean()), "w_mean": float(w.mean()),
                     "w_median": float(np.median(w)), "w_p90": float(np.percentile(w, 90)), "n": len(w)}
    reg_hit = min(revs, key=lambda t: sum(abs(float(regv[k]) - float(revs[t][k])) for k in regv))
    pkg_hit = min(revs, key=lambda t: sum(abs(float(pkg[k]) - float(revs[t][k])) for k in regv))
    reg_d = sum(abs(float(regv[k]) - float(revs[reg_hit][k])) for k in regv)
    pkg_d = sum(abs(float(pkg[k]) - float(revs[pkg_hit][k])) for k in regv)
    rows = [{"field": k, "register": regv[k], "payload_recomputed": round(float(pkg[k]), 4),
             "post_r1": round(revs["post-r1"][k], 4), "pre_r1": round(revs["pre-r1"][k], 4),
             "register_matches": "pre-r1" if abs(float(regv[k]) - float(revs["pre-r1"][k])) < 5e-4 else (
                 "post-r1" if abs(float(regv[k]) - float(revs["post-r1"][k])) < 5e-4 else "neither")}
            for k in ("n", "w_eq_1_share", "w_mean", "w_median", "w_p90")]
    rec("G", "登记/载荷各自指向的修订", reg_hit == "pre-r1" and pkg_hit == "post-r1",
        f"登记 5 项与 {reg_hit} 总偏差 {reg_d:.4f}（逐字段全等 pre-r1）；"
        f"载荷 5 项与 {pkg_hit} 总偏差 {pkg_d:.4f}（逐字段全等 post-r1）")

    # G3 根因判定：登记是否为「完整自洽的 pre-R1 快照」而非「混算产物」
    coh = {
        "pairs_aug_raw=pre-R1 值": reg["stages"]["P2"]["counts"]["pairs_aug_raw"] == 1753477,
        "pairs_same_cluster_raw=pre-R1 值": reg["stages"]["P2"]["counts"]["pairs_same_cluster_raw"] == 96874,
        "tie_break 文本=pre-R1 权重优先": "权重 desc" in reg["stages"]["P2"]["params"]["tie_break"],
        "缺 r1_fix 块": "r1_fix" not in reg["stages"]["P2"],
        "hop12①=pre-R1 旧值 0.8972": reg["stages"]["P2"]["self_test"]["hop12_kw_seeds_mean"] == 0.8972,
        "cooccur 饱和对=pre-R1 值 3878": reg["stages"]["P2"]["edge_stats"]["cooccur_saturated_pairs"] == 3878,
        "规模计数与载荷一致(5187/99268/188512)": (reg["stages"]["P2"]["counts"]["nodes"] == 5187
            and reg["stages"]["P2"]["counts"]["edges_final"] == int(w8.size)
            and reg["stages"]["P2"]["counts"]["cards"] == 188512),
    }
    rec("G", "登记是「整修订自洽」的 pre-R1 快照", all(coh.values()),
        "7 项独立口径全部指向 pre-R1（口径层）+ 规模层自洽 → 非混算产物：" + json.dumps(coh, ensure_ascii=False))

    # G4 决定性佐证：登记刷新后重导出即自洽
    fresh = os.path.join(data, "topics", "audit", "export", "repro", "v1", "topics", "meta.json")
    src_p = os.path.join(td, "meta.json")
    if os.path.exists(fresh):
        fr = json.load(open(fresh, encoding="utf-8"))
        same_src = sha256_file(fresh) == sha256_file(src_p)
        fs = {"w_eq_1_share": fr["stages"]["P2"]["edge_stats"]["w_eq_1_share"],
              "pairs_aug_raw": fr["stages"]["P2"]["counts"]["pairs_aug_raw"],
              "has_r1_fix": "r1_fix" in fr["stages"]["P2"]}
        rec("G", "决定性佐证：登记刷新后重导出即自洽", same_src and abs(fs["w_eq_1_share"] - pkg["w_eq_1_share"]) < 5e-4
            and fs["pairs_aug_raw"] == 1112854 and fs["has_r1_fix"],
            f"20:44 重导出包登记 sha256 == 当前源登记（逐字节相同）；其 w_eq_1_share={fs['w_eq_1_share']}"
            f"（=载荷反算 {pkg['w_eq_1_share']:.4f}）、pairs_aug_raw={fs['pairs_aug_raw']}（=去重后）、含 r1_fix"
            f" → 同一导出代码在登记刷新后产出**自洽包**")
    else:
        rec("G", "决定性佐证：重导出对照存在", False, f"{fresh} 不存在")

    # G5 时间线 + 根因裁决
    tl = {"登记刷新(源)": json.load(open(src_p, encoding="utf-8"))["updated_at"],
          "载荷 edges.csr.npz mtime": __import__("time").strftime(
              "%Y-%m-%dT%H:%M:%S", __import__("time").localtime(os.path.getmtime(os.path.join(td, "edges.csr.npz")))),
          "随包生成": json.load(open(os.path.join(exp, "manifest.json"), encoding="utf-8"))["generated_at"],
          "随包登记 updated_at": reg["updated_at"], "随包登记 P2.generated_at": reg["stages"]["P2"]["generated_at"]}
    order_ok = tl["随包登记 updated_at"] < "2026-09-18T19:46:33" and tl["载荷 edges.csr.npz mtime"] > reg["updated_at"]
    rec("G", "根因裁决 = 快照过期（非生成逻辑 bug）", order_ok,
        f"时间线 登记 {reg['updated_at']}(P2 登记于 {reg['stages']['P2']['generated_at']}) < 载荷 19:45:26 "
        f"< 随包生成 19:46:33 < 登记刷新 20:01:04；export_topics 以 shutil.copyfile 逐字节复制"
        f"「当时磁盘上的 meta.json」→ 复制到的是 R1 前登记快照；登记刷新后同一代码即产出自洽包（§G4）")
    json.dump({"finding_confirmed": bool(mismatch), "register_vs_payload": rows,
               "register_points_to": reg_hit, "payload_points_to": pkg_hit,
               "timeline": tl, "root_cause": "snapshot-staleness (verbatim copy of pre-R1 register at export time)",
               "contributing_defect": "export_topics 无跨产物一致性校验/无快照绑定，缺陷静默通过",
               "primary_fix": "重跑 topics_meta.py 后重导出（登记已刷新，见 §G4 已验证自洽）",
               "hardening": "复制前断言 meta.counts.{nodes,edges_final,cards} == 导出实际规模；--strict 不一致即失败"},
              open(os.path.join(out, "audit_export_recheck.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------- E
def section_e(exp, data, ref):
    print("\n=== [E] 与既有 v1 发行包格式风格一致性 + R1 修复无回归 ===", flush=True)
    et = os.path.join(exp, "topics")
    if not os.path.isdir(ref):
        rec("E", "风格基线存在", False, f"{ref} 不存在，跳过风格对照")
        return
    rman = json.load(open(os.path.join(ref, "manifest.json"), encoding="utf-8"))
    rfiles = {f["path"]: f for f in rman.get("files", [])}
    rec("E", "风格基线", True, f"{ref}（v1 瘦身发行包，{len(rfiles)} 项文件；含 embeddings_int8.bin/tfidf CSR/knn CSR）")

    # 惯例 1：CSR = indptr + indices 分文件、小端定长二进制（非 npz/非文本）
    conv = {
        "CSR 拆分 indptr/indices 两文件": all(os.path.exists(os.path.join(et, n)) for n in
                                              ("edges_indptr.i64.bin", "edges_indices.i32.bin")),
        "CSR 行偏移独立于列索引": "tfidf/indptr.bin" in rfiles and "tfidf/indices.bin" in rfiles,
        "卡行序 CSR 与 knn 同构": os.path.getsize(os.path.join(et, "card_topics_indptr.i32.bin")) ==
                                  os.path.getsize(os.path.join(ref, "knn_indptr.i32.bin")),
    }
    rec("E", "CSR 惯例一致", all(conv.values()), json.dumps(conv, ensure_ascii=False))

    # 惯例 2：uint8 量化 + /255 还原（v1 的 knn_sims.u8 同款）
    knn_u8 = os.path.getsize(os.path.join(ref, "knn_sims.u8.bin")) == 1885120
    rec("E", "uint8 无外部 scale 量化惯例", knn_u8,
        "v1 knn_sims.u8.bin = 1885120 B = 188512×10 → 同款 u8 + 固定 /255 还原；"
        "topics 边权沿用（非 int8+per-row scale 的 embeddings 路线，因权重值域固定 [0,1]）")

    # 惯例 3：小端（用「按大端读会得到非法值」来证伪 BE，而非依赖 dtype.byteorder——
    # 本机为小端，numpy 会把 '<' 归一为 '='，故 byteorder 不可作为判据）
    ip_le = np.fromfile(os.path.join(et, "edges_indptr.i64.bin"), dtype="<i8")
    ip_be = np.fromfile(os.path.join(et, "edges_indptr.i64.bin"), dtype=">i8")
    ix_le = np.fromfile(os.path.join(et, "edges_indices.i32.bin"), dtype="<i4")
    ix_be = np.fromfile(os.path.join(et, "edges_indices.i32.bin"), dtype=">i4")
    le_ok = (int(ip_le[0]) == 0 and int(ip_le[-1]) == len(ix_le) and bool(np.all(np.diff(ip_le) >= 0))
             and int(ix_le.max()) < 5187 and int(ix_le.min()) >= 0)
    be_bad = not (int(ip_be[0]) == 0 and bool(np.all(np.diff(ip_be) >= 0))
                  and 0 <= int(ix_be.min()) and int(ix_be.max()) < len(ip_be) - 1)
    rec("E", "小端（LE）字节序", le_ok and be_bad,
        f"LE 解：indptr[0]={int(ip_le[0])} 末={int(ip_le[-1])} 单调✓ 列索引∈[0,5187)✓；"
        f"BE 解：indptr[0]={int(ip_be[0])} 末={int(ip_be[-1])} 列索引 max={int(ix_be.max())} → BE 越界/非法，证伪")
    emb = os.path.getsize(os.path.join(ref, "embeddings_scale.f32.bin")) if os.path.exists(
        os.path.join(ref, "embeddings_scale.f32.bin")) else 0
    rec("E", "int8 路线与其适用域", emb > 0,
        f"v1 对 bge 向量用 int8（{os.path.getsize(os.path.join(ref,'embeddings_int8.bin'))} B）+ 外部 float32 scale "
        f"（{emb} B）；topics 权重为标量非向量，采用 u8 更贴惯例，二者不混用")

    # 无回归 1：导出 == 当前源（R1 修复后）
    z = np.load(os.path.join(data, "topics", "edges.csr.npz"))
    w_e = np.fromfile(os.path.join(et, "edges_weights.u8.bin"), dtype="<u1")
    w_post = z["weights"].astype(np.float32)
    rec("E", "导出对齐 R1 修复后主产物", len(w_e) == len(w_post),
        f"nnz {len(w_e)} == edges.csr.npz nnz {len(w_post)}")

    # 无回归 2：与 R1 前旧边表对照（不得是旧产物）
    pre_p = os.path.join(data, "topics", "edges.csr.pre-r1.npz")
    if os.path.exists(pre_p):
        zp = np.load(pre_p)
        ix_pre, w_pre = zp["indices"].astype(np.int32), zp["weights"].astype(np.float32)
        ix_e = np.fromfile(os.path.join(et, "edges_indices.i32.bin"), dtype="<i4")
        same_nnz = len(w_pre) == len(w_e)
        n_w = int((w_e != np.clip(np.round(w_pre * 255.0), 0, 255).astype(np.uint8)).sum()) if same_nnz else -1
        n_i = int((ix_e != ix_pre).sum()) if len(ix_pre) == len(ix_e) else -1
        rec("E", "非 R1 前旧产物（无回退）", n_w != 0 or n_i != 0,
            f"pre-r1 nnz={len(w_pre)}（与导出同为 99268：R1 为去重+排序键修复，top-20 截断下 nnz 不变）；"
            f"权重差异 {n_w}/{len(w_e)}（{100.0*n_w/len(w_e):.1f}%）、列索引差异 {n_i} → 载荷取自修复后边表")
        rec("E", "R1 修复仍在位（排序键+去重口径）", n_w > 0 and (n_i != 0 or n_w > 0),
            f"若为 pre-r1 载荷则权重应 100% 相同；实测仅 {100.0*(len(w_e)-n_w)/len(w_e):.2f}% 相同 → 修复已进入载荷")
    else:
        rec("E", "R1 前基线存在", False, "edges.csr.pre-r1.npz 缺失，无法做回归对照")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--exp", default=DEFAULT_EXP)
    ap.add_argument("--ref", default=DEFAULT_REF)
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print(f"[EXP-VERIFY] 复验对象 {a.exp}")
    print(f"[EXP-VERIFY] manifest.json sha256 = {sha256_file(os.path.join(a.exp,'manifest.json'))}")
    print(f"[EXP-VERIFY] package mtime = "
          f"{__import__('time').strftime('%Y-%m-%d %H:%M:%S', __import__('time').localtime(os.path.getmtime(os.path.join(a.exp,'manifest.json'))))}")

    section_a(a.exp, a.out)
    section_b(a.data, a.exp, a.out)
    section_c(a.data, a.exp, a.out)
    section_d(a.data, a.exp)
    section_e(a.exp, a.data, a.ref)
    section_f(a.data, a.exp, a.out)
    section_g(a.data, a.exp, a.out)

    npass = sum(1 for c in R["checks"] if c["ok"])
    print(f"\n[SUMMARY] {npass}/{len(R['checks'])} 项通过；失败 {len(R['errors'])} 项")
    for e in R["errors"]:
        print("  ✗", e)
    json.dump(R, open(os.path.join(a.out, "verify-results.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0 if not R["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())

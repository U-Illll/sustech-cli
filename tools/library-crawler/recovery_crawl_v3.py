#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recovery_crawl_v3 — 遗留缺口「递归细分补抓」轮（v3 根级并行版，2026-09-18）

v3 相对 v2（recovery_crawl_20260916.py）的改动——语义不变，仅并行化 + 线程安全：
1. 根级并行：最多 N_ROOTS 个根同时处理（ThreadPoolExecutor），单根内部保持 v2 递归逻辑
2. 全局写锁（WRITE_LOCK）：records.jsonl 追加 / recovery-progress.json 保存 均加锁
3. 日志锁：多线程写 recovery 日志与 scrape.log 均加锁
4. 速率不变：所有请求经共享 scrape.LIMITER（进程内全局，≤5 req/s 红线）
5. 断点兼容：同一 recovery-progress.json 格式（done 集合跳过已完成根）

用法:
  python3 recovery_crawl_v3.py                        # 正式补抓（全部剩余根，根并发 4）
  python3 recovery_crawl_v3.py --roots 6              # 指定根并发度
  python3 recovery_crawl_v3.py --only C912 --no-write # 干跑单个前缀（不落盘）
停止:
  pkill -f recovery_crawl_v3
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/tmp/library-scrape")
import scrape as S

BASE = Path("/tmp/library-scrape")
LOG_FILE = BASE / "recovery-20260916.log"
PROGRESS_FILE = BASE / "recovery-progress.json"
REPORT_FILE = BASE / "recovery-report-20260916.md"
CARDS = Path.home() / "go" / "lib-catalog-data" / "cards.jsonl"

SEG_LIMIT = 500          # guest 限制：offset+limit ≤ 500 → 单页最多 500
SORT = "title"
GHOST_HIT_THRESHOLD = 0.30
MAX_DEPTH = 6
PROBE_WORKERS = 4
# 细分字符集：数字、点、空格、斜杠、横杠、冒号、大写字母
CHARSET = " .-:/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

WRITE_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()

_logf = open(LOG_FILE, "a")


def rlog(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with LOG_LOCK:
        print(line, flush=True)
        _logf.write(line + "\n")
        _logf.flush()


def note_to_scrapelog(msg):
    with LOG_LOCK:
        with open(S.LOG_FILE, "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def load_json(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def save_json(p, obj):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    tmp.rename(p)


def q_of(prefix):
    return f"holding_call_number,begins_with,{prefix}"


def doc_hits(doc, prefix):
    for h in (doc.get("delivery", {}).get("holding", []) or []):
        c = h.get("callNumber") or ""
        if c.startswith(prefix):
            return True
    return False


def probe_node(prefix, stats):
    """探测节点真伪 + 总量（limit=3 + 头几条 call 真校验）。"""
    d = S.fetch(q_of(prefix), limit=3, offset=0, sort=SORT)
    stats["req"] += 1
    if d is None:
        return False, 0
    docs = d.get("docs", [])
    if not docs:
        return False, 0
    ok = any(doc_hits(x, prefix) for x in docs)
    t = d.get("info", {}).get("totalResultsLocal")
    t = t if isinstance(t, int) and t > 0 else len(docs)
    return ok, t


def fetch_segment(prefix, sort=SORT):
    """单页抓取（≤500）。返回 docs 或 None。"""
    d = S.fetch(q_of(prefix), limit=SEG_LIMIT, offset=0, sort=sort)
    if d is None:
        return None
    return d.get("docs", [])


def merge_docs(docs, prefix, got):
    for doc in docs:
        rec = S.extract_record(doc, prefix)
        if rec["mms"]:
            S.merge_rec(got, rec)


def probe_children(prefix, stats):
    """并发探测 prefix+X 的子块（真校验），返回 [(ch, total), ...]"""
    results = []

    def one(ch):
        ok, t = probe_node(prefix + ch, stats)
        if ok and t > 0:
            return (ch, t)
        return (ch, 0)

    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as ex:
        futs = [ex.submit(one, ch) for ch in CHARSET]
        for f in as_completed(futs):
            try:
                ch, t = f.result()
            except Exception:
                continue
            if t > 0:
                results.append((ch, t))
    results.sort(key=lambda x: -x[1])
    return results


def crawl_node(prefix, total, got, stats, depth=0):
    """递归细分补抓（token 已由 probe_node 校验，此处信任）。"""
    if total <= SEG_LIMIT:
        docs = fetch_segment(prefix)
        stats["req"] += 1
        if docs is None:
            stats["partial"].append(prefix)
            return
        merge_docs(docs, prefix, got)
        stats["leaves"] += 1
        return

    # total > 500：先抓第一页（保底），再细分
    docs = fetch_segment(prefix)
    stats["req"] += 1
    if docs is None:
        stats["partial"].append(prefix)
        return
    merge_docs(docs, prefix, got)

    if depth >= MAX_DEPTH:
        stats["deep"].append(prefix)
        return

    children = probe_children(prefix, stats)
    if not children:
        # 无法细分：多排序兜底
        for sort in ("date", "None", "creator"):
            sort_val = None if sort == "None" else sort
            d2 = S.fetch(q_of(prefix), limit=SEG_LIMIT, offset=0, sort=sort_val)
            stats["req"] += 1
            if d2 is None:
                continue
            merge_docs(d2.get("docs", []), prefix, got)
        stats["fallback"].append(prefix)
        return

    for ch, t in children:
        crawl_node(prefix + ch, t, got, stats, depth + 1)


def run_root(p, idx, total_n, cards_mms):
    """处理单个根（v2 main 循环体封装）。返回 (p, result_dict, got_dict)。"""
    t0 = time.time()
    stats = {"req": 0, "leaves": 0, "ghost": [], "partial": [], "deep": [], "fallback": []}
    got = {}
    ok, rt = probe_node(p, stats)
    rlog(f"[{idx}/{total_n}] {p}: 现 total={rt} ok={ok}")
    if not ok:
        stats["ghost"].append(p)
    elif rt > 0:
        crawl_node(p, rt, got, stats, depth=0)
    new_books = len(set(got) - cards_mms) if got else 0
    dt = time.time() - t0
    rlog(f"[{idx}/{total_n}] {p} → got={len(got)} unique | 新书 {new_books} | 请求 {stats['req']} | "
         f"leaves {stats['leaves']} | ghost {len(stats['ghost'])} | partial {len(stats['partial'])} | "
         f"fallback {len(stats['fallback'])} | {dt:.0f}s")
    result = {
        "status": "ok" if rt > 0 else "empty",
        "got": len(got), "new_books": new_books, "requests": stats["req"],
        "leaves": stats["leaves"], "ghosts": len(stats["ghost"]),
        "partial": len(stats["partial"]), "fallback": len(stats["fallback"]),
        "seconds": round(dt, 1),
    }
    return p, result, got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="只跑指定前缀（逗号分隔）")
    ap.add_argument("--no-write", action="store_true", help="不落盘（干跑）")
    ap.add_argument("--roots", type=int, default=4, help="根级并发度（默认 4）")
    args = ap.parse_args()

    prog = load_json(S.PROGRESS_FILE, {})
    gaps = prog.get("gaps", [])
    if args.only:
        wanted = set(args.only.split(","))
        roots = [g["p"] for g in gaps if g["p"] in wanted]
        for p in wanted:
            if p not in roots:
                roots.append(p)
    else:
        # leaf 先跑（快），branch 按 total 降序（产出大优先）
        leaves = [g["p"] for g in gaps if g.get("type") == "leaf"]
        branches = sorted([g for g in gaps if g.get("type") != "leaf"],
                          key=lambda g: -g.get("total", 0))
        roots = leaves + [g["p"] for g in branches]

    # 去重（保持顺序；gaps 内存在重复根）
    seen = set()
    dedup = []
    for p in roots:
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    roots = dedup

    rlog(f"=== RECOVERY START (v3 根级并行 x{args.roots}) === 根前缀 {len(roots)} 个（dry={args.no_write}）")
    note_to_scrapelog(f"=== 补缺轮 v3（recovery_crawl_v3 并行版·根并发 {args.roots}）启动：{len(roots)} 个遗留缺口前缀 ===")

    cards_mms = set()
    if CARDS.exists():
        with open(CARDS) as f:
            for line in f:
                try:
                    cards_mms.add(json.loads(line)["mms"])
                except Exception:
                    pass
    rlog(f"cards.jsonl 已加载 {len(cards_mms)} 个 mms（用于新书对账）")

    rp = load_json(PROGRESS_FILE, {"done": [], "results": {}})
    results = rp["results"]
    done = set(rp["done"])

    todo_roots = [p for p in roots if (p not in done) or args.only]
    rlog(f"待处理 {len(todo_roots)} 根（跳过已完成 {len(roots) - len(todo_roots)}）")

    all_got = {}
    n_fin = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=max(1, args.roots)) as ex:
        futs = {}
        for idx, p in enumerate(todo_roots, 1):
            futs[ex.submit(run_root, p, idx, len(todo_roots), cards_mms)] = p
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                p, result, got = fut.result()
            except Exception as e:
                rlog(f"!! {p} 异常: {type(e).__name__}: {str(e)[:120]}")
                result = {"status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}",
                          "got": 0, "new_books": 0, "requests": 0, "leaves": 0,
                          "ghosts": 0, "partial": 0, "fallback": 0, "seconds": 0}
                got = {}
            n_fin += 1
            with WRITE_LOCK:
                if got:
                    for m, rec in got.items():
                        all_got[m] = rec
                    if not args.no_write:
                        with open(S.RECORDS_FILE, "a") as f:
                            for rec in got.values():
                                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                results[p] = result
                if not args.no_write and not args.only:
                    done.add(p)
                    rp["done"] = sorted(done)
                    rp["results"] = results
                    save_json(PROGRESS_FILE, rp)
            el = time.time() - t_start
            rlog(f"进度 {n_fin}/{len(todo_roots)} 根完成（{p}）· 累计 {el:.0f}s")

    tot_got = len(all_got)
    tot_new = len(set(all_got) - cards_mms)
    tot_req = sum(r["requests"] for r in results.values())
    ghost = [k for k, r in results.items() if r["ghosts"]]
    lines = ["# 遗留缺口补抓报告（recovery_crawl_v3 根级并行版）", "",
             f"- 生成：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 根前缀（累计 results）：{len(results)}",
             f"- 本次进程抓取 unique mms：{tot_got}",
             f"- 其中为交付数据集之外的新书：{tot_new}",
             f"- 总请求数（累计）：{tot_req}",
             f"- 幽灵/失败节点涉及的根：{len(ghost)}", "",
             "| prefix | got | 新书 | 请求 | leaves | seconds |", "|---|---|---|---|---|---|"]
    for k in sorted(results, key=lambda x: -results[x]["new_books"]):
        r = results[k]
        lines.append(f"| {k} | {r['got']} | {r['new_books']} | {r['requests']} | {r['leaves']} | {r['seconds']} |")
    # 新书样例
    new_mms = sorted(set(all_got) - cards_mms)
    if new_mms:
        lines += ["", "## 新书样例（前 25 条）", ""]
        for m in new_mms[:25]:
            rec = all_got[m]
            h = (rec.get("holdings") or [{}])[0]
            lines.append(f"- {rec.get('title', '')[:60]} | {h.get('call', '')[:30]} | {m}")
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rlog(f"报告：{REPORT_FILE}")
    rlog(f"=== RECOVERY DONE === 本次抓取 {tot_got} unique / 新书 {tot_new} / 总请求 {tot_req}（累计）")
    note_to_scrapelog("=== 补缺轮 v3 结束（recovery_crawl_v3）：详见 recovery-report-20260916.md ===")


if __name__ == "__main__":
    main()

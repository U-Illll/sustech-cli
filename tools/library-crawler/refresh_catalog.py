#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_catalog.py — 图书馆目录「增量刷新」流水线（增量抓书 → 编译口径 → 归类到现有主题 → 增量包）

本脚本面向**已发布过一次目录/主题图之后**的日常更新场景：只把"新到馆的书"抓回来，
编译成与既有发行包同口径的 cards，并把这些新书**归类到现有的主题节点**上（不新增主题节点）。

=====================================================================================
一、增量抓取策略：为什么选「首字符桶 + sort=date + 已知 mms 早停」，而不是复用 scrape.py 的断点队列
=====================================================================================
现状盘点（读了 `scrape.py` v9 后）：
  * `scrape.py` 的框架是**首次全量**设计：从 `holding_call_number,begins_with,<prefix>` 出发，
    对 36 个首字符种子做「细分探测（probe_children）→ 叶子批量抓（scrape_leaf）→ 缺口补抓
    （final_recheck_round，GAP_TRIGGER=100）」，断点 `progress.json` 记录的是**任务队列进度**
    （todo/gaps/stats），收敛条件是"无新任务且无修复进展"。
  * 它每次运行都会把整棵 prefix 树重新走一遍：全量 188.5k 本书对应 **数万次** HTTP 请求。
增量场景下这样做是浪费 —— 每周新增通常只有几十到几百本。

因此本脚本采用 **date-sweep 早停**：
  1. 复用 Primo 的排序能力：`GET /primaws/rest/pub/pnxs?...&q=holding_call_number,begins_with,<桶>&sort=date&limit=500`
     其中 `sort=date` = 按**入藏/编目日期倒序**（`scrape.py` 的 SORTS 里已用过 "date"），
     所以每个桶的第 1 页就是"最新的 500 本"。
  2. 逐桶翻页，遇到**连续 `--stop-after-known`（默认 200）条已在库 mms** 即认定该桶已追平，翻页停止。
     → 稳态下每桶通常只需 1 页；全量刷新请求量 ≈ 桶数（36）+ 新增页数，通常 **< 100 次**。
  3. 新书如果落在**全新索书号前缀**（例如新开架位）也不会漏：首字符桶是全覆盖的（36 个桶覆盖
     所有以数字/字母开头的索书号），桶内按日期倒序必然先撞到新书。
  4. 断点续传：每个桶的 `offset / consecutive_known / done` 与全局统计写入 `state.json`（原子写）；
     重启后从上次页继续；同时用「已抓到的 mms 集合」做幂等去重（重复运行不会写重复记录）。

分工建议（README 有详述）：
  * **首次全量** → `scrape.py`（+ `recovery_crawl_v3.py` 补缺口）→ `process.py` → 编译链。
  * **日常增量** → 本脚本 `refresh_catalog.py`；缺口仍未补齐时才回退到 `recovery_crawl_v3.py`。

=====================================================================================
二、归类口径（硬约束：**绝不新增主题节点**）
=====================================================================================
新书 → 主题，只允许命中 `<catalog>/topics/nodes.json` 里**已有**的节点（kw 词表 5,158 个 +
cls 类目 349 个）。打分为"标题 token × 词权"：
  * 切词 `tokenize()`：英文/数字 token + 中文连续串 bigram（与 `catalog_vector.tokenize` 同源规则）
  * `merge_bigrams()`：链式合并重叠 bigram（"机器"+"器学"+"学习" → "机器学习"），与
    `build_graph.merge_bigrams(max_len=5, min_ratio=0.25)` 同规则
  * 候选 = 合并词 ∩ 词表 ∪ 标题 token ∩ 词表
  * 词权 score(term) = Σ idf(t)，t 取「term 的组成 token」（ASCII 精确命中；CJK 取相邻 bigram 之和）
  * 取 score 前 `--topics`（默认 5）个 **kw** 节点，平局按节点 id 升序（确定性）；
    cls 类目节点不占名额（与主题图 P2 口径一致，用于层级边）
  * idf 来源 `--idf-from auto`：优先 `<catalog>/index/idf.npy` + `vocab.json`（与发行索引同源），
    缺失时退化为**用 `<catalog>/cards.jsonl` 现算 df**（idf = log(N/(1+df))），并在报告里标注来源
  * **未入词表的高频新词不会成为节点**，只写进 `vocab_gap_report.json` 供人工决策（这是硬约束的落点）

=====================================================================================
三、速率与礼貌（≥ scrape.py 实测安全带）
=====================================================================================
`scrape.py` 的速率阶梯实验结论：**5.5 req/s 零错、8.5 req/s 开始 400**。
故本脚本 `--min-interval` 默认 **0.20s**（=5 req/s），硬下限 **0.18s**（=5.55 req/s，低于此值直接拒绝启动），
请求间加 0~30ms 抖动；遇到 400/401/403/429/5xx 时冷却 `15+10n` 秒并重试（最多 6 次）。

=====================================================================================
四、用法
=====================================================================================
  # 常规增量刷新（联机）
  python3 refresh_catalog.py --catalog ~/go/lib-catalog-data --out ./refresh-out

  # 离线：只处理一份已抓好的 records.jsonl（不联网；也是本脚本自测用的路径）
  python3 refresh_catalog.py --catalog ~/go/lib-catalog-data --records-from records.jsonl --out ./refresh-out

  # 解析器自测（用罐头 Primo 响应验证字段提取，不联网）
  python3 refresh_catalog.py --fixture-docs fixtures/primo_page.json --catalog ... --out ...

  # 全链路自检（内置断言，不联网）
  python3 refresh_catalog.py --self-test

产物（`--out` 目录）：
  records_delta.jsonl       新增原始记录（逐行，含 holdings 明细）
  cards_delta.jsonl         新增书卡（与 cards.jsonl **同字段同口径**）
  card_topics_delta.jsonl   新书 → 主题（`{"mms","topics":[id...]}`，可直接追加到 card_topics.jsonl）
  card_topics_delta.readable.tsv  同上的人类可读版（含主题词与分数）
  vocab_gap_report.json     未入词表的高频新词（**仅供人工决策，不会自动新增节点**）
  manifest.json             计数 / sha256 / 参数 / 观测到的日期范围
  MERGE.md                  合并指引（怎么并入现有发行包）
  state.json                断点（原子写）

依赖：`requests`（联机模式）；`--idf-from index` 时需要 `numpy`。
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import random
import re
import ssl
import string
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# 本机工具链的 numpy 环境（社区环境无此目录时自动跳过，届时 --idf-from 会回退 cards.jsonl 现算）
_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)

# =====================================================================================
# 0. 常量（与 scrape.py / compile_cards.py 对齐）
# =====================================================================================
HOST = "https://sustc.primo.exlibrisgroup.com.cn"
VID = "86SUSTC_INST:86SUSTC"
INST = "86SUSTC_INST"
PNX_URL = "/primaws/rest/pub/pnxs"

DEFAULT_MIN_INTERVAL = 0.20      # = 5.0 req/s（scrape.py 实测 5.5 req/s 零错）
MIN_INTERVAL_FLOOR = 0.18        # = 5.55 req/s 安全带下沿，低于此值拒绝启动
DEFAULT_LIMIT = 500              # Primo 单页上限
DEFAULT_STOP_AFTER_KNOWN = 200   # 连续命中已知 mms 多少条即认为该桶追平
DEFAULT_MAX_PAGES = 20
DEFAULT_MAX_REQUESTS = 2000
DEFAULT_BUCKETS = string.digits + string.ascii_uppercase
HTTP_RETRY_STATUS = (400, 401, 403, 429, 500, 502, 503, 504)
GAP_REPORT_TOP = 50              # vocab_gap_report 保留的高频未登录词条数

# 与 compile_cards.py 完全一致（vendored，便于本包独立运行）
COLLECTION_CODES = {"ER", "OC", "VI", "CTC", "MCC", "NKWK", "WGS", "PLY"}
T_SUBCLASSES = {"TB", "TD", "TE", "TF", "TG", "TH", "TJ", "TK", "TL", "TM",
                "TN", "TP", "TQ", "TS", "TU", "TV", "TX", "TY", "TZ"}
CN_RE = re.compile(r"^([A-Za-z]+)(.*)$")
LATIN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LIB_NAMES = {"LYNN": "琳恩图书馆", "yidan": "一丹图书馆", "library_3": "涵泳图书馆"}


def log(msg, quiet=False):
    if not quiet:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# =====================================================================================
# 1. HTTP 层（速率安全带 / 退避 / 断点友好）——与 scrape.py v9 同算法
# =====================================================================================
class RateLimiter:
    """全局最小间隔 + 冷却期；与 scrape.py v9 的 RateLimiter 同算法（含 0~30ms 抖动）。"""

    def __init__(self, min_interval):
        self.lock = threading.Lock()
        self.min_interval = min_interval
        self.next_time = 0.0
        self.cooldown_until = 0.0

    def acquire(self):
        with self.lock:
            now = time.time()
            t = max(now, self.next_time, self.cooldown_until)
            self.next_time = t + self.min_interval + random.uniform(0, 0.03)
        wait = t - now
        if wait > 0:
            time.sleep(wait)

    def cooldown(self, sec):
        with self.lock:
            target = time.time() + sec
            if target > self.cooldown_until:
                self.cooldown_until = target


def make_session():
    """老 TLS 兼容会话（Primo 站点需要 OP_LEGACY_SERVER_CONNECT，同 scrape.py）。"""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context

    class LegacyTLSAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = create_urllib3_context()
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
            kwargs["ssl_context"] = ctx
            return super().init_poolmanager(*args, **kwargs)

    s = requests.Session()
    s.trust_env = False
    s.mount("https://", LegacyTLSAdapter(pool_connections=4, pool_maxsize=4))
    return s


class Fetcher:
    """带速率安全带与退避的取数器；统计请求数以便 --max-requests 预算控制。"""

    def __init__(self, min_interval, timeout=60, max_requests=DEFAULT_MAX_REQUESTS, quiet=False):
        self.limiter = RateLimiter(min_interval)
        self.timeout = timeout
        self.max_requests = max_requests
        self.requests_made = 0
        self.session = make_session()
        self.quiet = quiet

    def budget_left(self):
        return self.max_requests - self.requests_made

    def fetch(self, q, limit=1, offset=0, sort=None, retries=6):
        """返回 JSON dict 或 None；语义与 scrape.py.fetch 相同。"""
        if self.budget_left() <= 0:
            raise RuntimeError(f"达到 --max-requests 预算（{self.max_requests}），停止取数")
        params = {"vid": VID, "tab": "default_tab", "scope": "MyInstitution", "q": q,
                  "limit": str(limit), "offset": str(offset), "lang": "zh_CN",
                  "mode": "Basic", "getMore": 0, "inst": INST}
        if sort:
            params["sort"] = sort
        for att in range(retries):
            self.limiter.acquire()
            self.requests_made += 1
            try:
                r = self.session.get(HOST + PNX_URL, params=params, timeout=self.timeout,
                                     headers={"Accept": "application/json",
                                              "User-Agent": "Mozilla/5.0 (catalog-refresh)"})
                if r.status_code == 200:
                    return r.json()
                if r.status_code in HTTP_RETRY_STATUS:
                    wait = 15 + att * 10
                    log(f"    HTTP {r.status_code} q={q[:40]!r} cooldown {wait}s ({att + 1})", self.quiet)
                    self.limiter.cooldown(wait)
                    time.sleep(wait)
                    continue
                log(f"    HTTP {r.status_code} fatal q={q[:60]!r}", self.quiet)
                return None
            except Exception as e:                      # noqa: BLE001 - 网络异常一律退避重试
                log(f"    EXC {type(e).__name__}: {str(e)[:60]} q={q[:40]!r}", self.quiet)
                self.limiter.cooldown(10)
                time.sleep(5 + att * 5)
        log(f"    请求最终失败 q={q[:50]!r}", self.quiet)
        return None


# =====================================================================================
# 2. 记录层（与 scrape.py.extract_record / merge_rec 同口径）
# =====================================================================================
def extract_record(doc, prefix=""):
    disp = doc.get("pnx", {}).get("display", {})

    def g(k):
        v = disp.get(k, [])
        return v[0] if v else ""

    rec = {"mms": g("mms"), "title": g("title"), "creator": g("creator"),
           "publisher": g("publisher"), "year": g("creationdate"),
           "language": g("language"), "type": g("type"), "prefix": prefix, "holdings": []}
    for h in (doc.get("delivery", {}).get("holding", []) or []):
        rec["holdings"].append({
            "lib": h.get("libraryCode", ""), "main": h.get("mainLocation", ""),
            "sub": h.get("subLocation", ""), "sub_code": h.get("subLocationCode", ""),
            "call": h.get("callNumber", ""), "status": h.get("availabilityStatus", ""),
        })
    return rec


def merge_rec(got, rec):
    """同 mms 合并馆藏（去重 lib/sub/call），与 scrape.py.merge_rec 同规则。"""
    prev = got.get(rec["mms"])
    if prev is None:
        got[rec["mms"]] = rec
        return
    seen = {(h["lib"], h["sub"], h["call"]) for h in prev["holdings"]}
    for h in rec["holdings"]:
        key = (h["lib"], h["sub"], h["call"])
        if key not in seen:
            prev["holdings"].append(h)
            seen.add(key)


def clean_multi(v):
    """清洗 Primo 多值字段（$$Q/$$T… 分隔符 + 去重）——process.py 同口径。"""
    if isinstance(v, list):
        v = "$$Q".join(str(x) for x in v)
    if not isinstance(v, str):
        return ""
    parts = re.split(r"\$\$[A-Z]", v)
    seen = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.append(p)
    return "; ".join(seen)


def parse_shelf(call):
    """从索书号提取书架位置——process.py.parse_shelf 同口径。"""
    if not call:
        return ""
    c = call.strip()
    m = re.search(r"第\s*(\d+)\s*排\s*([ABCD])\s*面", c)
    if m:
        return f"第{m.group(1)}排{m.group(2)}面"
    m = re.search(r"第\s*(\d+)\s*排(?!\s*[ABCD]\s*面)", c)
    if m:
        return f"第{m.group(1)}排"
    m = re.search(r"第\s*(\d+)\s*架(?:\s*Shelf\s*No\.?\s*(\d+))?", c)
    if m:
        return f"第{m.group(1)}架(Shelf No.{m.group(2)})" if m.group(2) else f"第{m.group(1)}架"
    return ""


# =====================================================================================
# 3. 卡片层（与 compile_cards.py 同口径：cn/cls/cls2 解析 + 字段集合）
# =====================================================================================
def classify_cn(call_number):
    """从完整索书号解析 (cn, cls, cls2)——compile_cards.py.classify_cn 的逐字副本。

    标准中图法（A121 / TP311.13 / I247.57）、复分号（B-53 / TU-092.2）、
    馆藏代码（CTC:B / MCC:B / NKWK / ER / OC / VI）保留；外文小说作者排架码（ZOL/AUS2…）解析为空。
    """
    s = (call_number or "").strip()
    if not s:
        return "", "", ""
    first = re.split(r"[\s/]", s, maxsplit=1)[0]
    if not first:
        return "", "", ""
    m = re.match(r"^([A-Za-z]{2,8}):([A-Za-z]+)$", first)
    if m:
        code, sub = m.group(1).upper(), m.group(2).upper()
        return f"{code}:{sub}", code, sub
    m = CN_RE.match(first)
    letters, rest = m.group(1).upper(), m.group(2)
    rest_ok = (bool(re.fullmatch(r"[0-9][0-9.]*(?:-[0-9][0-9.]*)*|-[0-9][0-9.]*", rest))
               if rest else False)
    if len(letters) == 1:
        if rest == "":
            return letters, letters, letters
        if rest_ok:
            if rest.startswith("-"):
                return letters + rest, letters, letters
            d1 = next(c for c in rest if c.isdigit())
            return letters + rest, letters, letters + d1
        return "", "", ""
    if len(letters) == 2:
        if rest_ok:
            if rest.startswith("-"):
                return letters + rest, letters, letters
            d1 = next(c for c in rest if c.isdigit())
            return letters + rest, letters, letters + d1
        if rest == "" and letters in COLLECTION_CODES:
            return letters, letters, letters
        return "", "", ""
    if letters in COLLECTION_CODES:
        return letters, letters, letters
    return "", "", ""


def is_std_cls(code):
    """标准中图法学科（单字母大类 或 T 类二级）——compile_cards.py 同口径。"""
    return len(code) == 1 or code in T_SUBCLASSES


CARD_FIELDS = ("mms", "title", "creator", "publisher", "year", "language", "type",
               "hc", "loc", "cn", "cls", "cls2", "src")


def record_to_card(rec):
    """records 记录 → cards.jsonl 口径的卡片。

    * title/creator/publisher 走 clean_multi（$$Q 分隔符清洗）；title 额外把 `$$Q` 还原为空格，
      与 `topic_build.iter_card()` 的消费方式一致。
    * hc = 馆藏条数；loc = 各馆藏 "馆名/子库/书架" 以 "; " 连接（process.py books.csv locations 同格式）
    * cn/cls/cls2 = 对**第一条有索书号的馆藏**调用 classify_cn（同 compile_cards 用 catalog_full 的 call_number）
    * src 固定 "main"（本包只处理主馆藏；特藏清单不在此路径）
    """
    holdings = rec.get("holdings") or []
    locs, call = [], ""
    for h in holdings:
        shelf = parse_shelf(h.get("call", ""))
        lib = LIB_NAMES.get(h.get("lib", ""), h.get("lib", ""))
        part = f"{lib}/{h.get('sub', '')}"
        if shelf:
            part += f"/{shelf}"
        locs.append(part)
        if not call and h.get("call"):
            call = h["call"]
    cn, cls, cls2 = classify_cn(call)
    return {
        "mms": rec.get("mms", ""),
        "title": clean_multi(rec.get("title", "")).replace("$$Q", " "),
        "creator": clean_multi(rec.get("creator", "")),
        "publisher": clean_multi(rec.get("publisher", "")),
        "year": clean_multi(rec.get("year", "")),
        "language": clean_multi(rec.get("language", "")),
        "type": clean_multi(rec.get("type", "")),
        "hc": len(holdings),
        "loc": "; ".join(locs),
        "cn": cn, "cls": cls, "cls2": cls2, "src": "main",
    }


# =====================================================================================
# 4. 分词与主题归类（硬约束：只用现有节点，不新增）
# =====================================================================================
def _bigram(seg):
    if len(seg) == 1:
        return [seg]
    return [seg[i:i + 2] for i in range(len(seg) - 1)]


def _cjk_bigrams(text):
    out, buf = [], ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            buf += ch
        else:
            if buf:
                out.extend(_bigram(buf))
            buf = ""
    if buf:
        out.extend(_bigram(buf))
    return out


def tokenize(text):
    """英文/数字 token + 中文连续串 bigram——catalog_vector.tokenize 同规则。"""
    low = (text or "").lower()
    tokens = [m.group(0) for m in LATIN_RE.finditer(low)]
    pos = 0
    for m in LATIN_RE.finditer(low):
        tokens.extend(_cjk_bigrams(low[pos:m.start()]))
        pos = m.end()
    tokens.extend(_cjk_bigrams(low[pos:]))
    return tokens


def _is_cjk(tok):
    return bool(tok) and bool(CJK_RE.match(tok[0]))


def merge_bigrams(scored, max_len=5, min_ratio=0.25):
    """链式合并重叠 CJK bigram——build_graph.merge_bigrams 同规则。scored: [(score, token)] 降序。"""
    used, merged = set(), []
    for s, t in scored:
        if t in used:
            continue
        if not _is_cjk(t):
            merged.append((s, t))
            used.add(t)
            continue
        cur, cur_s = t, s
        used.add(t)
        while len(cur) < max_len:
            tail, nxt = cur[-1], None
            for s2, t2 in scored:
                if t2 in used or not _is_cjk(t2):
                    continue
                if t2[0] == tail and s2 >= cur_s * min_ratio:
                    nxt = (s2, t2)
                    break
            if not nxt:
                break
            cur = cur + nxt[1][1:]
            used.add(nxt[1])
        merged.append((cur_s, cur))
    merged.sort(reverse=True)
    return merged


def term_score(term, tok_w):
    """score(card, term) = Σ 词权(组成 token)；ASCII 精确命中，CJK 取相邻 bigram 之和。"""
    if _is_cjk(term):
        if len(term) < 2:
            return tok_w.get(term, 0.0)
        return sum(tok_w.get(term[j:j + 2], 0.0) for j in range(len(term) - 1))
    return tok_w.get(term, 0.0)


def load_nodes(catalog):
    p = Path(catalog) / "topics" / "nodes.json"
    if not p.exists():
        sys.exit(f"[refresh] 找不到主题词表 {p}（本脚本需要 topics/nodes.json 才能做归类）")
    nodes = json.loads(p.read_text(encoding="utf-8"))
    nodes.__dict__ if False else None          # noqa: B018 - 保持 nodes 为纯 list
    kw_map, cls_map = {}, {}
    for n in nodes:
        t = n["term"]
        if n.get("type") == "cls":
            cls_map[t] = n["id"]
            cls_map.setdefault(t.lower(), n["id"])
        else:
            kw_map[t] = n["id"]
    return nodes, kw_map, cls_map


def load_idf(catalog, cards_path, idf_from="auto", quiet=False):
    """返回 (idf: dict[token->float], vocab_size, source)。
    auto: 优先 <catalog>/index/idf.npy + vocab.json（与发行索引同源）；缺失则用 cards.jsonl 现算 df。"""
    idx = Path(catalog) / "index"
    if idf_from in ("auto", "index") and (idx / "idf.npy").exists() and (idx / "vocab.json").exists():
        try:
            import numpy as np
            vocab = json.loads((idx / "vocab.json").read_text(encoding="utf-8"))
            idf = np.load(idx / "idf.npy")
            d = {t: float(idf[i]) for i, t in enumerate(vocab) if i < len(idf)}
            log(f"[idf] 来源 index/idf.npy（{len(d):,} 词）", quiet)
            return d, len(d), "index"
        except Exception as e:                       # noqa: BLE001
            log(f"[idf] index 读取失败（{type(e).__name__}: {e}），回退 cards.jsonl 现算", quiet)
    if idf_from == "index":
        sys.exit("[refresh] --idf-from index 但 index/idf.npy 或 vocab.json 不可用")
    df, n = Counter(), 0
    with open_cards(cards_path) as f:
        for line in f:
            if not line.strip():
                continue
            n += 1
            for t in set(tokenize(json.loads(line).get("title", ""))):
                df[t] += 1
    d = {t: math.log(n / (1.0 + c)) for t, c in df.items()}
    log(f"[idf] 来源 cards.jsonl 现算 df（{n:,} 卡 / {len(d):,} 词）", quiet)
    return d, len(d), "catalog"


def vocab_terms_in_title(title, kw_map, max_term_len=16):
    """枚举**标题中出现的词表项**（硬约束：只取 kw_map 里已有的词，绝不新造）。

    为什么不用 merge_bigrams 单独做候选：链式合并的起点取决于 token 排序，
    可能从中间 bigram 起链（"器学"→"器学习"）而漏掉完整词（"机器学习"）。
    这里改为对标题的每段 CJK 连续串做长度 2..max_term_len 的子串枚举 + 词表命中，
    对 5k 量级词表既完备又廉价（O(段长 × 最大词长) 次集合查询）。"""
    found = set()
    for seg in re.findall(r"[\u4e00-\u9fff]+", title or ""):
        L = len(seg)
        for i in range(L):
            for ln in range(2, min(max_term_len, L - i) + 1):
                w = seg[i:i + ln]
                if w in kw_map:
                    found.add(w)
    return found


def unlisted_phrases(title, vocab, max_len=6):
    """标题中"极大的未登录 CJK 子串"（左右再扩一位即已登录或越界）——用于 vocab_gap_report。"""
    out = set()
    for seg in re.findall(r"[\u4e00-\u9fff]+", title or ""):
        L = len(seg)
        for i in range(L):
            for ln in range(2, min(max_len, L - i) + 1):
                w = seg[i:i + ln]
                if w in vocab:
                    continue
                if ln < max_len and i + ln < L and seg[i:i + ln + 1] not in vocab:
                    continue                                   # 右扩一位仍未登录 → 不是极大
                if ln < max_len and i > 0 and seg[i - 1:i + ln] not in vocab:
                    continue                                   # 左扩一位仍未登录 → 不是极大
                out.add(w)
    return out


def classify_card(card, kw_map, idf, top_topics=5, top_m=10):
    """把一张卡归类到**已有**主题节点。返回 (topic_ids, detail)；detail=[(score, id, term)]。

    硬约束：只从 kw_map 取 id，任何情况下都不会产生新节点（未登录词只进 gap 报告）。
    候选 = 标题中出现的词表 CJK 词（子串枚举）∪ 标题 token 命中的词表项（含 ASCII 词）
    词权 = Σ idf(该词的组成 token)（ASCII 精确命中；CJK 取相邻 bigram 之和）
    """
    title = (card.get("title", "") or "").replace("$$Q", " ")
    toks = tokenize(title)
    tok_w = {}
    for t in toks:
        tok_w[t] = tok_w.get(t, 0.0) + idf.get(t, 1.0)          # 标题内 tf × idf
    cand = vocab_terms_in_title(title, kw_map)
    for t in toks:
        if t in kw_map:
            cand.add(t)
    scored = [(term_score(wd, tok_w), kw_map[wd], wd) for wd in cand]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:top_topics]
    return [i for _s, i, _t in top], top


# =====================================================================================
# 5. 目录读取 / 断点 / 产物写出
# =====================================================================================
def open_cards(path):
    """透明读取 cards.jsonl 或 cards.jsonl.gz。"""
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def find_cards(catalog):
    for name in ("cards.jsonl", "cards.jsonl.gz"):
        p = Path(catalog) / name
        if p.exists():
            return p
    return None


def atomic_write_json(path, obj):
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def read_known_mms(cards_path, quiet=False):
    known = set()
    n = 0
    with open_cards(cards_path) as f:
        for line in f:
            if not line.strip():
                continue
            n += 1
            m = json.loads(line).get("mms")
            if m:
                known.add(m)
    log(f"[catalog] 已入库 {n:,} 卡（唯一 mms {len(known):,}）", quiet)
    return known, n


# =====================================================================================
# 6. 阶段 A：增量抓取（date-sweep + 已知 mms 早停 + 断点）
# =====================================================================================
def stage_fetch(args, state, known, out_dir, quiet=False):
    """逐桶 date-sweep；新记录追加写 records_delta.jsonl，state 原子更新。返回新增记录数。"""
    fetcher = Fetcher(args.min_interval, timeout=args.timeout,
                      max_requests=args.max_requests, quiet=quiet)
    rec_path = Path(out_dir) / "records_delta.jsonl"
    already = set()
    if rec_path.exists():                                  # 断点续跑：已在 delta 里的 mms 不重复写
        with open(rec_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    already.add(json.loads(line).get("mms", ""))
    n_new, fh = 0, open(rec_path, "a", encoding="utf-8")
    try:
        for bucket in args.buckets:
            st = state["buckets"].setdefault(bucket, {"offset": 0, "consecutive_known": 0, "done": False})
            if st["done"]:
                continue
            for _page in range(st.get("page_count", 0), args.max_pages):
                if st["consecutive_known"] >= args.stop_after_known:
                    st["done"] = True
                    break
                q = f"holding_call_number,begins_with,{bucket}"
                d = fetcher.fetch(q, limit=args.limit, offset=st["offset"], sort="date")
                if d is None:
                    log(f"  [桶 {bucket}] 取数失败，保留断点待下次续跑", quiet)
                    break
                docs = d.get("docs", []) or []
                total = (d.get("info") or {}).get("totalResultsLocal")
                batch = {}
                for doc in docs:
                    rec = extract_record(doc, prefix=bucket)
                    if rec["mms"]:
                        merge_rec(batch, rec)
                fresh = 0
                for m, rec in batch.items():
                    if m in known or m in already:
                        st["consecutive_known"] += 1
                        continue
                    st["consecutive_known"] = 0
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    already.add(m)
                    fresh += 1
                    n_new += 1
                st["offset"] += len(docs)
                st["page_count"] = st.get("page_count", 0) + 1
                st["total"] = total
                state["stats"]["requests"] = fetcher.requests_made
                state["stats"]["records_new"] = state["stats"].get("records_new", 0) + fresh
                atomic_write_json(args.state, state)
                log(f"  [桶 {bucket}] offset={st['offset']} total={total} 本页 {len(docs)} 条 / 新增 {fresh} / "
                    f"连续已知 {st['consecutive_known']} / 请求累计 {fetcher.requests_made}", quiet)
                if fresh == 0 and len(docs) < args.limit:
                    st["done"] = True
                    break
                if not docs:
                    st["done"] = True
                    break
                if fresh == 0:
                    continue
                if fetcher.budget_left() <= 0:
                    log("  预算用尽，保留断点", quiet)
                    st["done"] = False
                    break
            if st["consecutive_known"] >= args.stop_after_known:
                st["done"] = True
            state["stats"]["requests"] = fetcher.requests_made
            atomic_write_json(args.state, state)
    finally:
        fh.close()
    log(f"[stage A] 增量抓取完成：新增记录 {n_new} 条 / 请求 {fetcher.requests_made} 次", quiet)
    return n_new


def load_records(path, quiet=False):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    log(f"[stage A] 离线读取记录 {len(recs)} 条 ← {path}", quiet)
    return recs


def records_from_fixture(path, quiet=False):
    """罐头 Primo 响应（`{"docs":[...]}` 或 `{"pages":[{...}]}`）→ 记录列表；用于离线自测解析器。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pages = data.get("pages") if isinstance(data, dict) and "pages" in data else [data]
    got = {}
    for pg in pages:
        for doc in (pg.get("docs") or []):
            rec = extract_record(doc, prefix=(pg.get("bucket") or ""))
            if rec["mms"]:
                merge_rec(got, rec)
    log(f"[fixture] 从罐头响应解析出 {len(got)} 条记录", quiet)
    return list(got.values())


# =====================================================================================
# 7. 阶段 B/C/D：编译卡片 / 归类 / 出包
# =====================================================================================
def stage_cards(records, known, out_dir, quiet=False):
    cards, skipped = [], 0
    for rec in records:
        if not rec.get("mms") or rec["mms"] in known:
            skipped += 1
            continue
        cards.append(record_to_card(rec))
    p = Path(out_dir) / "cards_delta.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    log(f"[stage B] 编译卡片 {len(cards)} 张（跳过已知/无 mms {skipped} 条）→ {p.name}", quiet)
    return cards


def stage_topics(cards, nodes, kw_map, idf, out_dir, args, quiet=False):
    """新书 → 现有主题；写 card_topics_delta.jsonl + 可读版 + 未登录词缺口报告。"""
    tp = Path(out_dir) / "card_topics_delta.jsonl"
    rp = Path(out_dir) / "card_topics_delta.readable.tsv"
    by_id = {n["id"]: n for n in nodes}
    gap, empty = Counter(), 0
    t0 = time.time()
    with open(tp, "w", encoding="utf-8") as f, open(rp, "w", encoding="utf-8") as g:
        g.write("mms\ttitle\ttopics\n")
        for c in cards:
            ids, detail = classify_card(c, kw_map, idf, top_topics=args.topics, top_m=args.top_m)
            f.write(json.dumps({"mms": c["mms"], "topics": ids}, ensure_ascii=False,
                               separators=(",", ":")) + "\n")
            readable = " | ".join(f"{by_id[i]['term']}({s:.2f})" for s, i, _t in detail)
            g.write(f"{c['mms']}\t{c['title']}\t{readable}\n")
            if not ids:
                empty += 1
            for t in set(tokenize(c["title"])):
                if t not in kw_map and len(t) >= 2:
                    gap[t] += 1
    # 把 bigram 碎片整理成"可决策的未登录短语"：
    #   * top_unlisted        —— 原始 bigram 计数（机械口径，不做任何猜测）
    #   * top_unlisted_phrases —— 标题里"极大的未登录 CJK 子串"（长 2..6，且左右再扩一位就变成已登录/越界），
    #                            再去掉被更长短语包含的项。例：词表有 主义/意识 而无 马克思主义 → 报 "马克思主义"。
    vocab_set = set(kw_map)
    phrases, drop = Counter(), set()
    for c in cards:
        for w in unlisted_phrases(c.get("title", ""), vocab_set, max_len=6):
            phrases[w] += 1
    kept = []
    for w, n in phrases.most_common(4000):
        if w in drop:
            continue
        kept.append((w, n))
        for i in range(len(w) - 1):
            for ln in range(2, len(w) - i + 1):
                drop.add(w[i:i + ln])
    vocab_gap = {
        "note": "以下为**未登录主题词表**的标题高频词（仅供人工评估是否值得在下一版 P1 里收录）；"
                "本脚本**不会**自动新增任何主题节点（硬约束）。phrases 为极大的未登录子串，bigrams 为原始碎片。",
        "cards": len(cards),
        "unlisted_token_types": len(gap),
        "top_unlisted_phrases": [{"phrase": w, "cards": n} for w, n in kept[:GAP_REPORT_TOP]],
        "top_unlisted_bigrams": [{"token": t, "cards": n} for t, n in gap.most_common(GAP_REPORT_TOP)],
    }
    atomic_write_json(Path(out_dir) / "vocab_gap_report.json", vocab_gap)
    log(f"[stage C] 归类完成 {len(cards)} 张卡（{time.time() - t0:.1f}s）：无主题 {empty} 张"
        f"（{100.0 * empty / max(len(cards), 1):.1f}%）／未登录词 {len(gap)} 类", quiet)
    return {"cards": len(cards), "cards_without_topics": empty,
            "empty_rate": round(empty / max(len(cards), 1), 4), "unlisted_token_types": len(gap)}


MERGE_TEMPLATE = """# 增量包合并指引（由 refresh_catalog.py 生成）

本目录是一个**增量包**（不是完整发行包）：只含本轮新增的书记录/卡片/主题归类。

## 0. 合并前检查
- `manifest.json`：`cards` 应为期望的新书数；`sha256` 可用于传输校验。
- `cards_delta.jsonl` 与现有 `cards.jsonl` **字段完全一致**（{fields}）。
- `vocab_gap_report.json` 列出未入词表的高频新词——**仅供人工决策**，本包不会新增主题节点。

## 1. 并入卡片（追加即可，mms 唯一）
```bash
cp cards.jsonl cards.jsonl.bak-$(date +%Y%m%d)          # 先备份
cat {out}/cards_delta.jsonl >> cards.jsonl
```

## 2. 并入主题归类（证据链，行序必须与 cards.jsonl 对齐）
`card_topics.jsonl` 的口径是"每卡一行、行序与 cards.jsonl 一致"。两种做法：

- **推荐（简单）**：把新卡追加到 cards.jsonl 之后，再把 `card_topics_delta.jsonl` 追加到
  `card_topics.jsonl` 末尾——因为增量卡也是追加在末尾，行序自然对齐。
  ```bash
  cat {out}/card_topics_delta.jsonl >> card_topics.jsonl
  ```
- **若你对 cards.jsonl 做过重排/去重**：请改为按 mms 归并，并重新跑一次主题图构建（见 §4）。

## 3. 校验
```bash
wc -l cards.jsonl card_topics.jsonl        # 两者行数必须相等
python3 - <<'PY'
import json
n = sum(1 for _ in open('cards.jsonl', encoding='utf-8'))
m = sum(1 for _ in open('card_topics.jsonl', encoding='utf-8'))
assert n == m, (n, m)
print('OK', n)
PY
```

## 4. 重建派生层（索引 / 图 / 主题图）
增量卡并入后，下列派生文件**不会自动更新**，需要维护者重跑（工具链不在本包内）：
`index/`（TF-IDF、embeddings、kNN 图）、`clusters*`、`topics/edges.csr.npz`。
社区使用者若只需"书 → 主题"查询，可**跳过本步**：查询层直接读 `cards.jsonl` + `card_topics.jsonl` 即可。

## 5. 回滚
```bash
mv cards.jsonl.bak-YYYYMMDD cards.jsonl     # 恢复卡片
# card_topics.jsonl 同理：合并前请另存一份
```
"""


def write_package(out_dir, args, records, cards, topic_stats, manifest_extra, quiet=False):
    out = Path(out_dir)
    files = {}
    for name in ("records_delta.jsonl", "cards_delta.jsonl", "card_topics_delta.jsonl",
                 "card_topics_delta.readable.tsv", "vocab_gap_report.json"):
        p = out / name
        if p.exists():
            files[name] = {"bytes": p.stat().st_size, "sha256": sha256_file(p)}
    manifest = {
        "tool": "refresh_catalog.py",
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "catalog": str(Path(args.catalog).resolve()),
        "out_dir": str(out.resolve()),
        "params": {"mode": args.mode, "limit": args.limit, "stop_after_known": args.stop_after_known,
                   "max_pages": args.max_pages, "min_interval": args.min_interval,
                   "topics_per_card": args.topics, "top_m": args.top_m, "idf_source": manifest_extra.get("idf_source")},
        "counts": {"records": len(records), "cards": len(cards), **topic_stats},
        "files": files,
        "hard_constraint": "只使用 topics/nodes.json 的既有节点做归类；不新增任何主题节点",
    }
    manifest.update(manifest_extra)
    atomic_write_json(out / "manifest.json", manifest)
    (out / "MERGE.md").write_text(
        MERGE_TEMPLATE.format(fields=" / ".join(CARD_FIELDS), out=str(out.resolve())), encoding="utf-8")
    log(f"[stage D] 增量包写出 → {out}（卡片 {len(cards)} / 归类 {topic_stats['cards']}）", quiet)
    return manifest


# =====================================================================================
# 8. 自检（不联网）
# =====================================================================================
def self_test(quiet=False):
    ok, fail = 0, 0

    def chk(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            log(f"  [PASS] {name}", quiet)
        else:
            fail += 1
            log(f"  [FAIL] {name} {detail}", quiet)

    # 1) 分词 / 合并
    chk("tokenize 中英混排", tokenize("Machine Learning 机器学习")[:3] == ["machine", "learning", "机器"],
        str(tokenize("Machine Learning 机器学习")[:3]))
    merged = [w for _s, w in merge_bigrams(sorted(((1.0, "机器"), (0.9, "器学"), (0.8, "学习")),
                                                  key=lambda x: -x[0]))]
    chk("merge_bigrams 链式合并", "机器学习" in merged, str(merged))
    # 2) 分类号解析（与 compile_cards 同口径）
    cases = [("A121", ("A121", "A", "A1")), ("TP311.13", ("TP311.13", "TP", "TP3")),
             ("B-53", ("B-53", "B", "B")), ("CTC:B", ("CTC:B", "CTC", "B")),
             ("NKWK", ("NKWK", "NKWK", "NKWK")), ("ZOL 第6架", ("", "", ""))]
    for raw, exp in cases:
        got = classify_cn(raw)
        chk(f"classify_cn({raw})", got == exp, f"期望 {exp} 实得 {got}")
    # 3) 卡片口径
    rec = {"mms": "TEST1", "title": "机器学习$$Q导论", "creator": "张三$$Q李四",
           "publisher": "北京 ; 某社", "year": "2026", "language": "chi", "type": "book",
           "holdings": [{"lib": "yidan", "sub": "3F", "call": "TP181/123 第3排A面"},
                        {"lib": "LYNN", "sub": "2F", "call": "TP181/123 第3排A面"}]}
    card = record_to_card(rec)
    chk("record_to_card 字段集合", tuple(card.keys()) == CARD_FIELDS, str(tuple(card.keys())))
    chk("record_to_card hc", card["hc"] == 2, str(card["hc"]))
    chk("record_to_card cn/cls", (card["cn"], card["cls"], card["cls2"]) == ("TP181", "TP", "TP1"),
        str((card["cn"], card["cls"], card["cls2"])))
    chk("record_to_card loc", "一丹图书馆" in card["loc"] and "第3排A面" in card["loc"], card["loc"])
    chk("record_to_card title 口径（clean_multi：多值以 \"; \" 连接，无残留 $$Q）",
        card["title"] == "机器学习; 导论" and "$$Q" not in card["title"], card["title"])
    # 4) 归类只用现有节点
    nodes = [{"id": 0, "term": "机器学习", "type": "kw", "freq": 10, "cluster": 1, "cls": "TP", "sources": ["B"]},
             {"id": 1, "term": "学习", "type": "kw", "freq": 20, "cluster": 1, "cls": "TP", "sources": ["B"]},
             {"id": 2, "term": "TP1", "type": "cls", "freq": 30, "cluster": 1, "cls": "TP1", "sources": ["C"]}]
    kw_map = {n["term"]: n["id"] for n in nodes if n["type"] == "kw"}
    ids, detail = classify_card({"mms": "T", "title": "机器学习$$Q导论"}, kw_map,
                                {"机器": 1.0, "器学": 1.0, "学习": 1.0, "导论": 0.5}, top_topics=5)
    chk("归类命中现有节点（完整词优先于碎片）", ids and ids[0] == 0 and 1 in ids, str(detail))
    chk("子串枚举不漏词", "机器学习" in vocab_terms_in_title("机器学习导论", kw_map),
        str(sorted(vocab_terms_in_title("机器学习导论", kw_map))))
    chk("归类不产生越界 id", all(0 <= i < len(nodes) for i in ids), str(ids))
    chk("cls 节点不占名额", 2 not in ids, str(ids))
    # 5) 速率安全带
    chk("min_interval 下限守护", MIN_INTERVAL_FLOOR >= 0.18 and DEFAULT_MIN_INTERVAL >= MIN_INTERVAL_FLOOR,
        f"{MIN_INTERVAL_FLOOR}")
    chk("5.5 req/s 安全带", 1.0 / MIN_INTERVAL_FLOOR <= 5.56, f"{1.0 / MIN_INTERVAL_FLOOR:.2f} req/s")
    log(f"[self-test] pass={ok} fail={fail}", quiet)
    return 0 if fail == 0 else 1


# =====================================================================================
# 9. main
# =====================================================================================
def main():
    ap = argparse.ArgumentParser(
        description="图书馆目录增量刷新（抓新书 → 编译卡片 → 归类到现有主题 → 增量包）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="增量策略与口径见文件头 docstring；硬约束：不新增主题节点。")
    ap.add_argument("--catalog", default=os.path.expanduser("~/go/lib-catalog-data"),
                    help="现有发行数据目录（需含 cards.jsonl[.gz] 与 topics/nodes.json）")
    ap.add_argument("--out", default=None, help="增量包输出目录（默认 <catalog>/refresh-<时间戳>）")
    ap.add_argument("--state", default=None, help="断点文件（默认 <out>/state.json）")
    ap.add_argument("--mode", choices=["date", "prefix", "both"], default="date",
                    help="date=按入藏日期倒序早停（增量推荐）；prefix=按索书号前缀字典序（会翻很多页）")
    ap.add_argument("--buckets", default=DEFAULT_BUCKETS, help="首字符桶（默认 0-9A-Z 共 36 个）")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="每页条数（Primo 上限 500）")
    ap.add_argument("--stop-after-known", type=int, default=DEFAULT_STOP_AFTER_KNOWN,
                    help="连续命中已知 mms 多少条即认为该桶已追平")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="每桶最大页数（安全阀）")
    ap.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL,
                    help=f"请求最小间隔秒（默认 {DEFAULT_MIN_INTERVAL}=5 req/s；硬下限 {MIN_INTERVAL_FLOOR}=5.55 req/s）")
    ap.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS, help="本次运行请求预算")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--topics", type=int, default=5, help="每卡归类主题数（与主题图 P2 口径一致，默认 5）")
    ap.add_argument("--top-m", type=int, default=10, help="标题 top-M token 参与合并（默认 10）")
    ap.add_argument("--idf-from", choices=["auto", "index", "catalog"], default="auto")
    ap.add_argument("--records-from", default=None, help="离线：直接处理一份 records.jsonl（不联网）")
    ap.add_argument("--fixture-docs", default=None, help="离线：解析罐头 Primo 响应 JSON（不联网）")
    ap.add_argument("--dry-run", action="store_true", help="只跑解析/归类，不写增量包（仍写 state）")
    ap.add_argument("--self-test", action="store_true", help="内置断言自检（不联网）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    quiet = args.quiet

    if args.self_test:
        sys.exit(self_test(quiet))

    # 速率护栏：低于安全带下沿直接拒绝（保护对端站点）
    if args.min_interval < MIN_INTERVAL_FLOOR:
        sys.exit(f"[refresh] --min-interval={args.min_interval} 低于安全带下沿 {MIN_INTERVAL_FLOOR}"
                 f"（= {1.0 / MIN_INTERVAL_FLOOR:.2f} req/s）。scrape.py 实测 5.5 req/s 零错、"
                 f"8.5 req/s 开始 400，请勿更快。")

    catalog = Path(os.path.expanduser(args.catalog))
    cards_path = find_cards(catalog)
    if cards_path is None:
        sys.exit(f"[refresh] 在 {catalog} 找不到 cards.jsonl 或 cards.jsonl.gz")
    out_dir = Path(os.path.expanduser(args.out)) if args.out else \
        catalog / f"refresh-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    args.out = str(out_dir)
    args.state = args.state or str(out_dir / "state.json")
    t0 = time.time()

    # 断点
    state = {"version": 1, "started": datetime.now().isoformat(timespec="seconds"),
             "catalog": str(catalog), "buckets": {}, "stats": {}}
    if Path(args.state).exists():
        try:
            state = json.loads(Path(args.state).read_text(encoding="utf-8"))
            log(f"[state] 续跑自 {args.state}（已完成桶 {sum(1 for b in state.get('buckets', {}).values() if b.get('done'))} 个）", quiet)
        except Exception as e:                        # noqa: BLE001
            log(f"[state] 断点损坏（{e}），重新开始", quiet)
    state.setdefault("buckets", {})
    state.setdefault("stats", {})

    known, n_cards = read_known_mms(cards_path, quiet)
    nodes, kw_map, cls_map = load_nodes(catalog)
    idf, vocab_n, idf_src = load_idf(catalog, cards_path, args.idf_from, quiet)
    log(f"[topics] 词表 {len(nodes):,} 节点（kw {len(kw_map):,} / cls {len(cls_map):,}）；"
        f"idf {vocab_n:,} 词（来源 {idf_src}）", quiet)

    # ---- 阶段 A：取数 ----
    if args.records_from:
        records = load_records(os.path.expanduser(args.records_from), quiet)
    elif args.fixture_docs:
        records = records_from_fixture(os.path.expanduser(args.fixture_docs), quiet)
    else:
        stage_fetch(args, state, known, out_dir, quiet)
        records = load_records(out_dir / "records_delta.jsonl", quiet)

    # ---- 阶段 B/C/D ----
    cards = stage_cards(records, known, out_dir, quiet)
    topic_stats = stage_topics(cards, nodes, kw_map, idf, out_dir, args, quiet)
    nodes_path = Path(args.catalog) / "topics" / "nodes.json"
    manifest_extra = {
        "idf_source": idf_src, "known_cards": n_cards, "elapsed_s": round(time.time() - t0, 1),
        # topic id 的语义只在某一版词表下成立 → 必须记录词表指纹，便于日后对齐/回溯
        "vocab": {"file": "topics/nodes.json", "nodes": len(nodes),
                  "kw": len(kw_map), "cls": len(cls_map),
                  "nodes_sha256": sha256_file(nodes_path) if nodes_path.exists() else None},
    }
    if args.dry_run:
        log("[dry-run] 不写 manifest/MERGE.md（其余产物已生成，便于检查）", quiet)
    else:
        write_package(out_dir, args, records, cards, topic_stats, manifest_extra, quiet)
    atomic_write_json(args.state, state)
    log(f"[done] {len(cards)} 张新卡 / {topic_stats['cards_without_topics']} 张无主题 / "
        f"{time.time() - t0:.1f}s → {out_dir}", quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())

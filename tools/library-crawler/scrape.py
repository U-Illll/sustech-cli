#!/usr/bin/env python3
"""SUSTech 图书馆全馆藏抓取器 v9 - 并发加速版（基于 v8，语义不变仅提速）
v9 相对 v8 的改动：
1. scrape_leaf: 首个排序先行（经济路径），不足时剩余排序并行补齐（原来为三种排序串行）
2. process_queue: "先抓一笔"与"细分探测"并行执行（原来串行）
3. recheck_chars: 每字符的 rank/title 双查询并行（原来串行+双 pause）
4. PROBE_WORKERS 3→4；MIN_INTERVAL 0.28→0.15（依速率阶梯实验定标）
队列/断点/收敛/日志格式与 v8 完全兼容（"全部完成"等字样不变）。
"""
import ssl, json, time, random, string, threading, sys
import requests
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

BASE = Path("/tmp/library-scrape")
OUT = BASE / "output"
OUT.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = OUT / "progress.json"
RECORDS_FILE = OUT / "records.jsonl"
LOG_FILE = OUT / "scrape.log"

HOST = "https://sustc.primo.exlibrisgroup.com.cn"
VID = "86SUSTC_INST:86SUSTC"
INST = "86SUSTC_INST"
CHARSET = list(string.digits) + list(string.ascii_uppercase)
LEAF_MAX = 490
BULK_LIMIT = 500
PROBE_WORKERS = 4          # v9: 3→4
LEAF_WORKERS = 3           # v9 新增：叶子补抓并行度
MIN_INTERVAL = 0.20        # v9: 0.28→0.20（速率实验：5.5req/s零错 / 8.5req/s现400 → 取安全带）
SORTS = ["title", None, "date"]
GAP_TRIGGER = 100
LEAF_RETRY_MAX = 2

LOG_LOCK = threading.Lock()
def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with LOG_LOCK:
        print(line, flush=True)
        with open(LOG_FILE, 'a') as f:
            f.write(line + "\n")

class RateLimiter:
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

LIMITER = RateLimiter(MIN_INTERVAL)

class LegacyTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.mount('https://', LegacyTLSAdapter(pool_connections=10, pool_maxsize=10))

def fetch(q, limit=1, offset=0, sort=None, retries=6):
    params = {"vid": VID, "tab": "default_tab", "scope": "MyInstitution", "q": q,
              "limit": str(limit), "offset": str(offset), "lang": "zh_CN",
              "mode": "Basic", "getMore": 0, "inst": INST}
    if sort:
        params["sort"] = sort
    url = HOST + "/primaws/rest/pub/pnxs"
    for att in range(retries):
        LIMITER.acquire()
        try:
            r = SESSION.get(url, params=params,
                            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                            timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 401, 403, 429, 500, 502, 503, 504):
                wait = 15 + att * 10
                log(f"    HTTP {r.status_code} q={q[:38]!r} cooldown {wait}s ({att+1})")
                LIMITER.cooldown(wait)
                time.sleep(wait)
                continue
            log(f"    HTTP {r.status_code} fatal q={q[:60]!r}")
            return None
        except Exception as e:
            log(f"    EXC {type(e).__name__}: {str(e)[:60]} q={q[:38]!r}")
            LIMITER.cooldown(10)
            time.sleep(5 + att * 5)
    log(f"    请求最终失败 q={q[:50]!r}")
    return None

def get_total(prefix, sort=None):
    d = fetch(f"holding_call_number,begins_with,{prefix}", limit=1, offset=0, sort=sort)
    if d is None:
        return None
    return d['info'].get('totalResultsLocal')

def save_progress(prog):
    tmp = PROGRESS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(prog, ensure_ascii=False, indent=1))
    tmp.rename(PROGRESS_FILE)

def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return None

def extract_record(doc, prefix):
    disp = doc.get('pnx', {}).get('display', {})
    def g(k):
        v = disp.get(k, [])
        return v[0] if v else ''
    rec = {
        'mms': g('mms'),
        'title': g('title'),
        'creator': g('creator'),
        'publisher': g('publisher'),
        'year': g('creationdate'),
        'language': g('language'),
        'type': g('type'),
        'prefix': prefix,
        'holdings': []
    }
    for h in (doc.get('delivery', {}).get('holding', []) or []):
        rec['holdings'].append({
            'lib': h.get('libraryCode', ''),
            'main': h.get('mainLocation', ''),
            'sub': h.get('subLocation', ''),
            'sub_code': h.get('subLocationCode', ''),
            'call': h.get('callNumber', ''),
            'status': h.get('availabilityStatus', ''),
        })
    return rec

def merge_rec(got, rec):
    prev = got.get(rec['mms'])
    if prev is None:
        got[rec['mms']] = rec
        return
    seen = {(h['lib'], h['sub'], h['call']) for h in prev['holdings']}
    for h in rec['holdings']:
        key = (h['lib'], h['sub'], h['call'])
        if key not in seen:
            prev['holdings'].append(h)
            seen.add(key)

def scrape_leaf(prefix, total, deep_retry=True):
    """v9: 首个排序先行；不足时剩余排序并行补齐。deep_retry=True 时不足则冷却再试一轮。"""
    got = {}
    max_rounds = 2 if deep_retry else 1
    q = f"holding_call_number,begins_with,{prefix}"
    for rnd in range(max_rounds):
        # 第 1 个排序（经济路径：多数叶子一发即全）
        d = fetch(q, limit=BULK_LIMIT, offset=0, sort=SORTS[0])
        if d is not None:
            for doc in d.get('docs', []):
                rec = extract_record(doc, prefix)
                merge_rec(got, rec)
        if len(got) < total - 2:
            # 缺 → 剩余排序并行补齐
            rest = SORTS[1:]
            def do_fetch(sort):
                return fetch(q, limit=BULK_LIMIT, offset=0, sort=sort)
            with ThreadPoolExecutor(max_workers=LEAF_WORKERS) as ex:
                futs = [ex.submit(do_fetch, s) for s in rest]
                for fut in as_completed(futs):
                    try:
                        dd = fut.result()
                    except Exception as e:
                        log(f"    叶子补抓异常 {prefix!r}: {e}")
                        continue
                    if dd is None:
                        continue
                    for doc in dd.get('docs', []):
                        rec = extract_record(doc, prefix)
                        merge_rec(got, rec)
        if len(got) >= total - 2:
            break
        if rnd < max_rounds - 1:
            LIMITER.cooldown(30)
            time.sleep(30)
    with open(RECORDS_FILE, 'a') as f:
        for rec in got.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True, len(got)

def probe_children(prefix):
    results = {}
    pending = set(CHARSET)
    zero_chars = set()
    for rnd in range(3):
        if not pending:
            break
        to_probe = sorted(pending)
        pending = set()
        failed_now = set()
        def probe(c):
            t = get_total(prefix + c)
            return c, t
        with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as ex:
            futs = [ex.submit(probe, c) for c in to_probe]
            for fut in as_completed(futs):
                c, t = fut.result()
                if t is None:
                    failed_now.add(c)
                elif t > 0:
                    results[prefix + c] = t
                else:
                    zero_chars.add(c)
        pending = failed_now
        if pending:
            log(f"    探测失败 {len(pending)} 字符，30s 后重试（轮 {rnd+1}）")
            LIMITER.cooldown(30); time.sleep(30)
    return sorted(results.items()), sorted(zero_chars | pending)

def recheck_chars(parent, chars, gap_target, max_chars=15, miss_limit=5, pause=0.5):
    """v9: 每字符的双排序查询并行（去字符内 pause）。返回发现的 (sub,total)。"""
    found = []
    misses = 0
    for c in chars:
        if len(found) >= max_chars or gap_target <= 0:
            break
        if misses >= miss_limit:
            break
        sub = parent + c
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(get_total, sub)
            f2 = ex.submit(get_total, sub, "title")
            t1 = f1.result(); t2 = f2.result()
        t = max(t1 or 0, t2 or 0)
        if t > 0:
            found.append((sub, t))
            gap_target -= t
            misses = 0
            log(f"      复验命中 {sub!r}: rank={t1} title={t2}")
        else:
            misses += 1
        time.sleep(pause)
    return found

def process_queue(prog):
    todo = prog['todo']
    while todo:
        item = todo[0]
        prefix = item['p']
        total = item.get('total')
        if total is None:
            t = get_total(prefix)
            if t is None:
                log(f"探测失败 {prefix!r}，跳过")
                todo.pop(0); save_progress(prog); continue
            total = t
            item['total'] = t
            save_progress(prog)

        if total == 0:
            todo.pop(0); save_progress(prog); continue

        if total <= LEAF_MAX:
            ok, got = scrape_leaf(prefix, total, deep_retry=True)
            shortfall = total - got
            tol = max(2, int(total * 0.015))
            if shortfall > tol and item.get('retry', 0) < LEAF_RETRY_MAX:
                item['retry'] = item.get('retry', 0) + 1
                log(f"叶子 {prefix!r} 缺 {shortfall}/{total}，延迟重试 #{item['retry']}")
                todo.append(todo.pop(0))
                save_progress(prog)
                LIMITER.cooldown(45); time.sleep(45)
                continue
            note = "" if shortfall <= tol else f"  <<< 缺口 {shortfall}"
            if shortfall > 0:
                note += f" [差{shortfall}]"
            log(f"叶子 {prefix!r} total={total} 唯一={got}{note}")
            prog['stats']['leaves'] += 1
            prog['stats']['records'] += got
            if shortfall > tol:
                prog['gaps'].append({'p': prefix, 'total': total, 'got': got, 'type': 'leaf'})
            todo.pop(0)
            save_progress(prog)
        else:
            # 1) 先抓一笔（数据保险）＋ 2) 细分探测  —— v9: 并行执行
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_pre = ex.submit(scrape_leaf, prefix, total, False)
                f_probe = ex.submit(probe_children, prefix)
                try:
                    ok, pre = f_pre.result()
                except Exception as e:
                    log(f"    先抓异常 {prefix!r}: {e}")
                    ok, pre = False, 0
                try:
                    kids, zero_chars = f_probe.result()
                except Exception as e:
                    log(f"    探测异常 {prefix!r}: {e}")
                    kids, zero_chars = [], []
            if pre > 0:
                log(f"    先抓 {prefix!r}: {pre} 条落盘")
            covered = sum(t for _, t in kids)
            gap = total - covered
            # 3) 大缺口 → 当场复验
            if gap > max(GAP_TRIGGER, int(total * 0.02)):
                log(f"    缺口 {gap}（大），冷却 20s 后当场复验 {len(zero_chars)} 字符")
                LIMITER.cooldown(20); time.sleep(20)
                found = recheck_chars(prefix, zero_chars, gap)
                for sub, t in found:
                    if sub not in [k for k, _ in kids]:
                        kids.append((sub, t))
                        covered += t
                gap = total - covered
            dt = time.time() - t0
            kid_info = ", ".join(f"{s}:{t}" for s, t in sorted(kids)[:14])
            log(f"细分 {prefix!r} (total={total}) -> {len(kids)}子块 覆盖{covered} 缺口{gap} [{dt:.0f}s] {kid_info}")
            item['children'] = [s for s, t in kids]
            item['covered'] = covered
            item['gap'] = gap
            if gap > max(GAP_TRIGGER, int(total * 0.02)):
                prog['gaps'].append({'p': prefix, 'total': total, 'covered': covered,
                                     'gap': gap, 'chars': zero_chars, 'type': 'branch'})
            todo.pop(0)
            for s, t in reversed(kids):
                todo.insert(0, {'p': s, 'total': t})
            save_progress(prog)

def final_recheck_round(prog):
    """终局修复轮：对全部遗留 gaps 慢速重修。返回 (修复数, 仍缺数)"""
    gaps = prog.get('gaps', [])
    if not gaps:
        return 0, 0
    fixed = 0
    remaining = []
    log(f"=== 终局修复轮：{len(gaps)} 个遗留缺口 ===")
    for gap in gaps:
        p = gap['p']
        total = gap['total']
        tol = max(2, int(total * 0.015))
        if gap.get('type') == 'leaf':
            ok, got = scrape_leaf(p, total, deep_retry=True)
            if got >= total - tol:
                fixed += 1
                log(f"  终局修复叶子 {p!r}: {got}/{total} ✓")
            else:
                gap['got'] = max(gap.get('got', 0), got)
                log(f"  终局修复叶子 {p!r} 仍缺: {got}/{total}")
                remaining.append(gap)
        else:  # branch
            chars = gap.get('chars', CHARSET)
            if not chars:
                chars = CHARSET
            g = gap.get('gap')
            if g is None:  # 兼容无 gap 字段的遗留条目（如 AT2/AT3/AT4/AT5 仅有 total/got）
                g = max(0, total - gap.get('covered', gap.get('got', 0)))
            found = recheck_chars(p, chars, g, max_chars=20, miss_limit=6, pause=0.6)
            if found:
                fixed += len(found)
                for sub, t in reversed(found):
                    prog['todo'].append({'p': sub, 'total': t})
                cov = gap.get('covered', 0) + sum(t for _, t in found)
                gap['covered'] = cov
                if total - cov > max(GAP_TRIGGER, int(total * 0.02)):
                    remaining.append(gap)
                else:
                    log(f"  终局修复分支 {p!r} 已补齐（{cov}/{total}）")
            else:
                remaining.append(gap)
    prog['gaps'] = remaining
    save_progress(prog)
    log(f"  终局轮：修复 {fixed}，仍缺 {len(remaining)}")
    return fixed, len(remaining)

def main():
    args = sys.argv[1:]
    prog = load_progress()
    if prog is None:
        seeds = args if args else list(string.ascii_uppercase)
        log(f"初始化队列，种子：{seeds}")
        baseline = get_total("")
        log(f"全量基线: {baseline}")
        prog = {'todo': [{'p': s, 'total': None} for s in seeds],
                'stats': {'leaves': 0, 'records': 0},
                'gaps': [],
                'baseline': baseline,
                'started': datetime.now().isoformat()}
        save_progress(prog)

    log(f"=== scrape v9 并发加速版启动（MIN_INTERVAL={MIN_INTERVAL} PROBE_WORKERS={PROBE_WORKERS}）===")
    round_num = 0
    while True:
        round_num += 1
        log(f"--- 主循环第 {round_num} 轮 ---")
        process_queue(prog)
        fixed, remaining = final_recheck_round(prog)
        pending = len(prog['todo'])
        if pending == 0 and fixed == 0:
            log("收敛：无新任务且无修复进展，结束")
            break
        if round_num > 12:
            log("达最大轮数（12），停止")
            break

    log(f"全部完成！stats={prog['stats']}")
    if prog['gaps']:
        log(f"=== 最终遗留缺口 ({len(prog['gaps'])}) ===")
        for g in prog['gaps']:
            log(f"  {g}")

if __name__ == '__main__':
    main()

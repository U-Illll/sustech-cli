#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_build.py — P1 主题节点抽取器（三源合一；产出 topics/nodes.json）

源 A: clusters.json 400 簇 keywords（归一/去重/停用词后保留）
源 B: index/tfidf.npz + vocab.json
      - 每卡取标题字段内 TF-IDF 最高 top-M（默认 10，范围 8-12）token
      - 用 build_graph.merge_bigrams 链式合并（与簇关键词同源词形逻辑），
        消除"济学/工智"这类无意义 bigram
      - 全局词频 df >= min_df（默认 12，与 argparse 一致；见报告中的阈值决策）
      - 中文 B-only 词需通过 A 词表/学科词表校验（保守抗噪，见 report）
源 C: cards.jsonl 的 CLC cls2 类目（type=cls）

节点 schema（§3.1）:
  {"id","term","type":"kw|cls","freq","cluster","cls","sources"}

R2-A 修复（2026-09-18，依据 topics/audit/p1/REPORT.md F1/F1b/F2/F2b）:
  F2/F2b: 长词包含率证据 ext_df 改为按卡片去重——A 源扩展证据与 B-CJK 扩展证据合并为同一趟、
          共用同一个 ext_seen（修复前两趟对同一卡同一扩展词各 +1，ext_df 可超过卡片数，
          包含率出现 >1.0，129 个 A 源词被误判为"跨词碎片"剔除）。
  F1/F1b: 截断排序键 _score 由 `freq * (max_cc/freq)` 的浮点乘积改为精确整数值
          （== 主导簇卡数；原式与 max_cc 可差 1 ulp，使 (-freq, term) 次级键失效、
          并由 1 ulp 噪声决定 --max-nodes 的截断边界）。

用法:
  python3 topic_build.py [--data DIR] [--out DIR] [--top-per-card 10]
                         [--min-df 12] [--max-nodes 20000] [--seed 42]
                         [--report topics/p1-build-report.json]
                         [--sample-out topics/p1-sample50-candidates.txt]
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from catalog_vector import tokenize                 # 同源分词，禁止另写
from build_graph import STOP_TOKENS, _STOP_RE, merge_bigrams

try:  # sklearn 标准英文停用词表（环境自带；无网络依赖）
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS as _SK_STOP
except Exception:
    _SK_STOP = set()
_PROTECTED_SK_STOP = {"system", "interest"}  # 领域词保护
_SK_STOP = set(_SK_STOP) - _PROTECTED_SK_STOP

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")

# ---------------------------------------------------------------------------
# 停用词/泛词表（在 build_graph.STOP_TOKENS 之上扩展；写进 build report/meta）
# ---------------------------------------------------------------------------
EXTRA_STOPWORDS = {
    # 中文出版/著录泛词与功能词
    "丛书", "文集", "全集", "选集", "汇编", "丛刊", "文库", "系列", "丛集",
    "第一", "第二", "第三", "第四", "第五", "第六", "第七", "第八", "第九", "第十",
    "上册", "下册", "上卷", "中卷", "下卷", "一卷", "二卷", "三卷", "四卷",
    "初级", "中级", "高级", "简明", "新编", "图解", "入门", "指导", "实用",
    "教程", "教材", "读本", "手册", "指南", "大全", "全书", "百科", "词典", "字典",
    "概论", "通论", "简史", "通史", "研究", "报告", "论文", "文选", "注释",
    "解读", "解析", "详解", "实例", "案例", "精选", "修订", "增订", "影印",
    "珍藏", "青少年", "中小学", "大学", "高等", "职业", "学校", "学生",
    "我的", "人的", "上的", "中的", "国的", "代的", "其应", "的应",
    "与", "及", "和", "的", "了", "是", "在", "为", "等", "之", "其",
    "本", "第", "上", "下", "中", "到", "从", "让", "把", "被", "由",
    # 英文功能词/出版泛词（STOP_TOKENS 已含冠词、介词、著录 boilerplate）
    "introduction", "intro", "volume", "vol", "handbook", "guide", "series",
    "advanced", "basic", "practical", "modern", "new", "short", "how", "using",
    "use", "used", "book", "books", "study", "studies", "research",
    "understanding", "perspective", "perspectives", "conference", "proceedings",
    "textbook", "manual", "edition", "revised", "complete", "selected", "essays",
    "papers", "notes", "lecture", "lectures", "course", "courses", "college",
    "university", "press", "publishing", "publishers", "academic", "springer",
    "wiley", "elsevier", "encyclopedia", "dictionary", "companion", "reader",
    "readings", "review", "reviews", "survey", "surveys", "progress", "advances",
    "trends", "current", "recent", "general", "collected", "works", "major",
}

# 英文功能词/学术泛词/序数词/缩写扩展
ENGLISH_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can't",
    "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    "doing", "don't", "down", "during", "each", "few", "for", "from",
    "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
    "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers",
    "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll",
    "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its",
    "itself", "let's", "me", "more", "most", "mustn't", "my", "myself", "no",
    "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
    "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's",
    "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're",
    "you've", "your", "yours", "yourself", "yourselves",
    # 出版/学术泛词
    "abstract", "acknowledgement", "acknowledgements", "afterword", "appendix",
    "bibliography", "chapter", "chapters", "conclusion", "contents", "foreword",
    "glossary", "index", "overview", "preface", "prologue", "epilogue",
    "references", "section", "sections", "summary", "supplement", "keywords",
    "volume", "volumes", "part", "parts", "edition", "editions", "series",
    "textbook", "manual", "handbook", "guide", "reader", "readings", "workbook",
    "monograph", "proceedings", "conference", "symposium", "workshop", "seminar",
    "lecture", "lectures", "course", "courses", "college", "university", "press",
    "publishing", "publisher", "publishers", "editor", "editors", "author",
    "authors", "editorial", "translation", "translations",
    # 通用动词/形容词/副词
    "show", "shows", "showed", "showing", "include", "includes", "including",
    "included", "present", "presents", "presented", "presenting", "provide",
    "provides", "provided", "providing", "make", "makes", "made", "making",
    "take", "takes", "took", "taking", "give", "gives", "gave", "giving",
    "find", "finds", "found", "finding", "see", "sees", "saw", "seen", "know",
    "knows", "knew", "known", "think", "thinks", "thought", "come", "comes",
    "came", "go", "goes", "went", "get", "gets", "got", "become", "becomes",
    "became", "sustaining", "sponsor", "sponsored", "sponsoring", "based",
    "via", "per", "etc", "eg", "ie", "cf", "vs", "versus", "toward", "towards",
    "within", "without", "upon", "among", "amongst", "throughout", "along",
    "across", "behind", "beside", "beyond", "despite", "except", "inside",
    "outside", "since", "although", "though", "whereas", "whether", "however",
    "therefore", "thus", "hence", "moreover", "furthermore", "nevertheless",
    "otherwise", "instead", "rather", "quite", "much", "many", "every",
    "either", "neither", "yet", "still", "even", "ever", "never", "always",
    "often", "sometimes", "usually", "generally", "particularly", "especially",
    "mainly", "mostly", "largely", "partly", "fully", "highly", "widely",
    "commonly", "typically", "new", "old", "good", "bad", "best", "better",
    "great", "small", "large", "little", "big", "long", "short", "high", "low",
    "fast", "slow", "easy", "hard", "simple", "complex", "difficult",
    "important", "major", "minor", "main", "primary", "secondary", "general",
    "specific", "particular", "certain", "various", "different", "similar",
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "one", "two", "three", "four", "five", "six",
    "seven", "eight", "nine", "ten", "eleven", "twelve", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "thousand", "million", "billion", "zero",
    # 缩写/地名代码
    "usa", "us", "uk", "u.k.", "u.s.", "u.s.a.", "ny", "n.j.", "s.", "w.",
    "l.", "ma", "vs.", "lab", "labs",
}
ROMAN_NUMERALS = {
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi",
    "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi",
    "xxii", "xxiii", "xxiv", "xxv", "xxx", "xl", "l", "lx", "lxx", "xc", "c",
    "cc", "cd", "d", "dc", "cm", "m", "mm", "mmm", "mmxx", "mmxxi",
}
EXTRA_STOPWORDS |= ENGLISH_STOPWORDS
EXTRA_STOPWORDS |= _SK_STOP
# 样本复核补入的泛词/残片（可调）
EXTRA_STOPWORDS |= {
    "ultimate", "midnight", "hands", "shared", "limitations", "pretest",
    "endangered", "ug", "pic", "的人", "新的", "旧的", "大的", "小的",
    "中的", "上的", "下的", "我的", "你的", "他的", "她的", "它的",
    "我们的", "你们的", "他们的", "人们的", "传媒经", "族卷",
    # 300 词诊断复核补入（英文泛词/人名/缩写）
    "classic", "private", "contexts", "engaging", "differences", "careers",
    "choosing", "combination", "told", "affair", "promises", "klick",
    "place", "talk", "moving", "characteristics", "articles", "mutual",
    "usage", "desire", "wonder", "shadows", "manners", "availability",
    "lucky", "hills", "preserving", "exploratory", "degrees", "generations",
    "updated", "sides", "direction", "figure", "talks", "realizing",
    "viewpoint", "ordered", "analyst", "reforming", "gaps", "superior",
    "limited", "devoted", "functioning", "twain", "juliet", "gatsby",
    "zhang", "lu", "fu",
    # v2 300 词诊断复核补入
    "age", "work", "states", "city", "brief", "elements", "complete",
    "those", "influence", "improving", "cooperation", "relationship",
    "population", "utilization", "problem", "problems", "issue", "issues",
    "teichm", "coching", "kants", "ulysses", "francaise", "akademie",
    "辑", "的政", "技术及", "那些", "材料的", "的旅", "的女人", "的工",
    "力和", "人在", "险的", "实的", "动与", "卷五", "龙八部",
    # 最终 50 词样本复核补入
    "investigation", "全译", "中英", "积极", "哲学与", "新唐", "双重",
    "民用",
    # 最终复核（min_df=12 抽样）
    "solutions", "description", "administrator", "negotiating", "millennium",
    "structuring", "breakthrough", "envisioning", "campaigns", "curie",
    "method", "methods", "number", "numbers", "question", "questions",
    "view", "views", "point", "points", "case", "cases", "example",
    "examples", "role", "roles", "result", "results", "effect", "effects",
    "impact", "impacts", "process", "processes", "activity", "activities",
    "condition", "conditions", "situation", "situations", "type", "types",
    "kind", "kinds", "area", "areas", "level", "levels", "period", "periods",
    "origin", "beginning", "ending", "change", "past", "today",
    "没有", "评论", "终结", "诞生", "崩溃", "探究", "决定", "简编",
    "中华文", "代通俗",
    # 最后一轮抽样复核
    "centuries", "wu", "追求", "事件", "漫长", "聚焦", "实操", "名家",
    "exploring", "transform", "transforms", "solved", "translating",
    "inspiration", "conversation", "economists", "schooling",
    "典型", "方向", "伟大", "情人", "探索", "现状", "战中", "讲记",
    "物图鉴", "一般", "工电工", "守护", "胜算", "state-of-the-art",
    "experience", "investigations", "competence", "unexpected", "italiano",
    "打造", "代文化", "学探", "四行",
    "excellence", "collecting", "interests", "report", "predicting",
    "例解", "选读", "图鉴", "分变函数", "忠实", "奥秘",
    "天然", "感悟", "完美", "术全",
    "alternative", "honor", "fantastic", "变革", "征服",
    "understand", "librarian", "physicist", "significance", "homme",
    "presentation", "interpretations", "大卫",
}
STOPWORDS = set(STOP_TOKENS) | EXTRA_STOPWORDS

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ALLOWED_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9_.\-]+$")
ASCII_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
ALNUM_RE = re.compile(r"^[A-Za-z0-9]{1,6}$")


def resolve_data(args):
    d = getattr(args, "data", None) or os.environ.get("LIB_CATALOG_DATA") or DATA_DEFAULT
    return os.path.abspath(os.path.expanduser(d))


def normalize_term(s):
    """NFKC 全半角统一 + 去空白；纯 ASCII 词统一小写（与 vocab 同口径）。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", "", s)
    if ASCII_RE.match(s):
        s = s.lower()
    return s.strip()


def normalize_cls(s):
    """CLC 类目码归一：NFKC + 去空白，保留大小写（如 TP3）。"""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", "", s).strip()


def term_ok_kw(s):
    if not (1 <= len(s) <= 16):
        return False
    if "." in s or s.startswith(("-", "_")) or s.endswith(("-", "_")):
        return False  # 点号缩写/句尾标点 token 视为噪声
    if not ALLOWED_RE.match(s):
        return False
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", s):
        return False
    if len(s) == 1:
        return False  # 单字主题噪声率高（含 CJK）
    if CJK_RE.search(s):
        if "的" in s and s not in {"目的", "标的", "的士", "的确"}:
            return False  # 含"的"的多为跨词残片/短语
        if len(s) >= 3 and (s[0] in "与及和" or s[-1] in "与及和"):
            return False  # 长词首尾为虚词："哲学与/技术及/力和"
        if len(s) == 2 and s[-1] == "与" and s not in {
                "参与", "涉及", "给与", "赠与", "付与", "相与"}:
            return False  # "验与/爱与/新与" 类残片
        if len(s) == 2 and s[0] == "与":
            return False  # "与影/与共" 类残片/虚词
        if s[-1] in "卷册篇編编":
            return False  # 卷册篇章等出版格式后缀："家学卷/绘畫編"
        if len(s) == 2 and s[-1] == "及" and s not in {
                "涉及", "普及", "波及", "遍及", "顾及", "不及", "以及", "埃及"}:
            return False
        if len(s) == 2 and s[-1] == "和" and s not in {
                "饱和", "中和", "总和", "柔和", "温和", "平和", "调和", "祥和",
                "和气", "和解", "和声", "和风", "和田", "和服", "和睦", "和约",
                "和好", "和缓", "和洽", "和悦", "和煦", "共和"}:
            return False
        if len(s) >= 3 and "之" in s:
            return False  # 含"之"的多为跨词短语："成功之"
    return True


def term_ok_cls(s):
    return bool(1 <= len(s) <= 16 and ALNUM_RE.match(s))


def is_stop(s):
    if s in STOPWORDS or _STOP_RE.match(s) or s.rstrip(".") in ROMAN_NUMERALS:
        return True
    if re.match(r"^\d+(st|nd|rd|th)(-century)?$", s) or re.match(r"^volume\d+$", s):
        return True
    if re.match(r"^[第]?[一二三四五六七八九十百千]+[卷册部篇]$", s):
        return True
    if re.match(r"^[一二三四五六七八九十百千]+$", s):
        return True
    if re.match(r"^第[0-9一二三四五六七八九十百千]+$", s):
        return True
    if re.match(r"^[0-9一二三四五六七八九十百千]+[卷册篇]$", s):
        return True
    if re.match(r"^[卷册篇][0-9一二三四五六七八九十百千]+$", s):
        return True
    return False


def top_title_tokens(card, indptr, indices, data, nv, title_tokens, top_m):
    """取该卡标题字段内 TF-IDF 最高的 top_m 个合法 token（确定性排序）。"""
    i = card
    a, b = int(indptr[i]), int(indptr[i + 1])
    pairs = []
    for p in range(a, b):
        k = nv[int(indices[p])]
        if k in title_tokens and term_ok_kw(k) and not is_stop(k):
            pairs.append((float(data[p]), k))
    pairs.sort(key=lambda x: (-x[0], x[1]))
    return pairs[:top_m]


def merged_card_words(pairs):
    """链式合并重叠 bigram -> 词（复用 build_graph.merge_bigrams）。"""
    words = set()
    for _s, w in merge_bigrams(pairs, max_len=5, min_ratio=0.25):
        w = normalize_term(w)
        if term_ok_kw(w) and not is_stop(w):
            words.add(w)
    return words


def load_source_a(clusters):
    """返回 (a_set, a_membership, raw_unique_count)。"""
    membership = defaultdict(Counter)
    raw = set()
    for cl in clusters:
        cid = int(cl.get("id"))
        for keyword in cl.get("keywords", []):
            k = normalize_term(keyword)
            raw.add(k)
            if term_ok_kw(k) and not is_stop(k):
                membership[k][cid] += 1
    return set(membership), membership, len(raw)


def load_subject_lexicon(subjects):
    lex = set()
    for c in subjects.get("classes", []):
        for part in re.split(r"[、，,;；/]", c.get("name", "")):
            k = normalize_term(part)
            if term_ok_kw(k) and not is_stop(k):
                lex.add(k)
    return lex


def build_a_matcher(a_set):
    """英文按 token 精确匹配；含 CJK 的按标题归一化串子串匹配（2-gram 前缀桶加速）。"""
    ascii_keys = {k for k in a_set if not CJK_RE.search(k)}
    cjk_keys = [k for k in a_set if CJK_RE.search(k)]
    single = {k for k in cjk_keys if len(k) == 1}
    buckets = defaultdict(list)
    for k in cjk_keys:
        if len(k) >= 2:
            buckets[k[:2]].append(k)
    return ascii_keys, single, buckets


def match_a(title, title_tokens, matcher, norm_title=None):
    ascii_keys, single, buckets = matcher
    found = set()
    for tok in title_tokens:
        if tok in ascii_keys:
            found.add(tok)
    if norm_title is None:
        norm_title = normalize_term(title)
    for ch in single:
        if ch in norm_title:
            found.add(ch)
    seen = set()
    for i in range(len(norm_title) - 1):
        bg = norm_title[i:i + 2]
        if bg in seen:
            continue
        seen.add(bg)
        for k in buckets.get(bg, ()):
            if k in norm_title:
                found.add(k)
    return found


def term_extensions(term, norm_title):
    """返回 term 在标题中的双向 1-2 字扩展（用于"长词包含率"碎片判定）。"""
    exts = set()
    L = len(term)
    start = 0
    while True:
        p = norm_title.find(term, start)
        if p < 0:
            break
        if p >= 1:
            exts.add(norm_title[p - 1] + term)
        if p + L < len(norm_title):
            exts.add(term + norm_title[p + L])
        if p >= 2:
            exts.add(norm_title[p - 2:p] + term)
        if p + L + 2 <= len(norm_title):
            exts.add(term + norm_title[p + L:p + L + 2])
        start = p + 1
    return {e for e in exts
            if e != term and len(e) <= L + 2 and CJK_RE.search(e) and term_ok_kw(e)}


def iter_card(cards_path, indptr):
    """逐行读 cards.jsonl，保证行序与 tfidf/clusters 对齐。"""
    with open(cards_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= len(indptr) - 1:
                break
            c = json.loads(line)
            title = (c.get("title") or "").replace("$$Q", " ")
            yield i, c, title, set(tokenize(title))


def main():
    ap = argparse.ArgumentParser(description="P1 主题节点构建（三源合一）")
    ap.add_argument("--data", default=None)
    ap.add_argument("--out", default=None, help="输出 topics 目录，默认 <data>/topics")
    ap.add_argument("--top-per-card", type=int, default=10, help="B 源每卡 top 词数（8-12）")
    ap.add_argument("--min-df", type=int, default=12, help="B 源英文 token 全局词频阈值")
    ap.add_argument("--min-df-cjk", type=int, default=15, help="B-only 中文合并词词频阈值")
    ap.add_argument("--en-min-freq", type=int, default=200, help="英文主题词质量闸门：最低书数")
    ap.add_argument("--en-min-cls-rep", type=float, default=0.6, help="英文主题词质量闸门：主一级分类占比")
    ap.add_argument("--en-min-len", type=int, default=9, help="英文主题词质量闸门：词长")
    ap.add_argument("--max-nodes", type=int, default=20000)
    ap.add_argument("--min-nodes", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sample-out", default=None, help="生成分层抽样候选文件")
    ap.add_argument("--sample-size", type=int, default=50, help="分层抽样数量（默认 50）")
    ap.add_argument("--report", default=None, help="构建报告 JSON 路径")
    args = ap.parse_args()

    D = resolve_data(args)
    out_dir = os.path.abspath(os.path.expanduser(args.out)) if args.out else os.path.join(D, "topics")
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()

    idx = os.path.join(D, "index")
    z = np.load(os.path.join(idx, "tfidf.npz"))
    indptr, indices, data = z["indptr"], z["indices"], z["data"]
    vocab = json.load(open(os.path.join(idx, "vocab.json"), encoding="utf-8"))
    labels = np.load(os.path.join(idx, "clusters.npy"))
    clusters = json.load(open(os.path.join(D, "clusters.json"), encoding="utf-8"))["clusters"]
    subjects = json.load(open(os.path.join(D, "subjects.json"), encoding="utf-8"))
    N = len(labels)
    nv = [normalize_term(t) for t in vocab]

    a_set, a_membership, a_raw = load_source_a(clusters)
    sub_lex = load_subject_lexicon(subjects)
    matcher = build_a_matcher(a_set)
    print(f"[load] N={N:,} V={len(vocab):,} nnz={len(indices):,} | "
          f"A raw={a_raw:,} kept={len(a_set):,} | subj_lex={len(sub_lex):,} | {time.time()-t0:.1f}s",
          flush=True)

    cards_path = os.path.join(D, "cards.jsonl")

    # ---- Pass 1：B 源 merged words 的 df ----
    # R2-A 修复 F2：本趟不再累计长词包含率证据（A 源扩展证据已并入 Pass 1.5 的同一 ext_seen）。
    b_df = Counter()
    ext_df = Counter()
    ext_candidates = defaultdict(set)
    n_cards = 0
    for i, _c, title, title_tokens in iter_card(cards_path, indptr):
        pairs = top_title_tokens(i, indptr, indices, data, nv, title_tokens, args.top_per_card)
        if pairs:
            for w in merged_card_words(pairs):
                b_df[w] += 1
        n_cards += 1
    b_df5 = sum(1 for v in b_df.values() if v >= 5)
    b_df8 = sum(1 for v in b_df.values() if v >= 8)
    b_df10 = sum(1 for v in b_df.values() if v >= 10)
    print(f"[pass1] cards={n_cards:,} B merged unique={len(b_df):,} | "
          f"df>=5:{b_df5:,} df>=8:{b_df8:,} df>=10:{b_df10:,} | {time.time()-t0:.1f}s", flush=True)

    b_keep = {w for w, v in b_df.items() if v >= args.min_df and term_ok_kw(w) and not is_stop(w)}
    b_keep_cjk = {w for w in b_keep if CJK_RE.search(w) and len(w) >= 2}

    # ---- Pass 1.5：长词包含率证据（A 源扩展 + B-CJK 扩展，同卡同一扩展词只计一次）----
    # R2-A 修复 F2/F2b：修复前 A 源扩展证据在 Pass 1 独立累计、B-CJK 扩展证据在本趟再累计，
    #   同一卡片的同一扩展词被 +2，ext_df 可超过卡片数 ⇒ containment_ratio 出现 >1.0
    #   （卡片级比值不可能 >1），129 个 A 源词仅因双计数越过 0.9 阈值被误判为跨词碎片剔除
    #   （见 topics/audit/p1/REPORT.md F2/F2b）。现合并为同一趟、共用 ext_seen ⇒ 按卡片去重。
    if True:
        n15 = 0
        for i, _c, title, title_tokens in iter_card(cards_path, indptr):
            pairs = top_title_tokens(i, indptr, indices, data, nv, title_tokens, args.top_per_card)
            norm_title = normalize_term(title)
            ext_seen = set()
            for w in match_a(title, title_tokens, matcher, norm_title):
                for e in term_extensions(w, norm_title):
                    ext_candidates[w].add(e)
                    ext_seen.add(e)
            if pairs and b_keep_cjk:
                for w in merged_card_words(pairs):
                    if w in b_keep_cjk:
                        for e in term_extensions(w, norm_title):
                            ext_candidates[w].add(e)
                            ext_seen.add(e)
            for e in ext_seen:
                ext_df[e] += 1
            n15 += 1
        print(f"[pass1.5] ext evidence (card-deduped): A_match+B-CJK terms={len(b_keep_cjk):,} "
              f"ext_unique={len(ext_df):,} | {time.time()-t0:.1f}s", flush=True)

    # ---- Pass 2：证据累计（freq / 主簇 / 主一级分类 / sources） ----
    freq = Counter()
    cl_counts = defaultdict(Counter)
    cls_counts = defaultdict(Counter)
    src_mask = defaultdict(int)
    c_keys = set()
    for i, c, title, title_tokens in iter_card(cards_path, indptr):
        pairs = top_title_tokens(i, indptr, indices, data, nv, title_tokens, args.top_per_card)
        words = merged_card_words(pairs) if pairs else set()
        keys = set()
        for w in words:
            if w in b_keep:
                keys.add(w)
                src_mask[w] |= 2  # B
        for w in match_a(title, title_tokens, matcher, normalize_term(title)):
            keys.add(w)
            src_mask[w] |= 1      # A
        cls2 = normalize_cls(c.get("cls2") or "")
        if term_ok_cls(cls2):
            keys.add(cls2)
            c_keys.add(cls2)
            src_mask[cls2] |= 4    # C
        if not keys:
            continue
        cluster = int(labels[i])
        cls1 = normalize_cls(c.get("cls") or "")
        for w in keys:
            freq[w] += 1
            cl_counts[w][cluster] += 1
            cls_counts[w][cls1] += 1
    for w in a_set:
        src_mask[w] |= 1
    print(f"[pass2] A={len(a_set):,} B_keep(df>={args.min_df})={len(b_keep):,} "
          f"C(cls2)={len(c_keys):,} | {time.time()-t0:.1f}s", flush=True)

    def mode_cluster(w):
        cc = cl_counts.get(w)
        if cc:
            return max(cc.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        mem = a_membership.get(w)
        if mem:
            return max(mem.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        return -1

    def fallback_cls_for_cluster(cid):
        if 0 <= cid < len(clusters):
            tops = clusters[cid].get("top_subjects") or []
            if tops:
                return str(tops[0][0])
        return ""

    def representativeness(w):
        cc = cl_counts.get(w)
        if not cc:
            mem = a_membership.get(w)
            if mem and sum(mem.values()) > 0:
                return max(mem.values()) / float(sum(mem.values()))
            return 0.0
        return max(cc.values()) / float(max(freq[w], 1))

    # A 源过滤：零频（无书目证据）与"长词包含率>=0.9"的跨词边界碎片
    def containment_ratio(w):
        f = freq.get(w, 0)
        if f <= 0:
            return 1.0
        best = 0.0
        for e in ext_candidates.get(w, ()):
            c = ext_df.get(e, 0)
            if c:
                best = max(best, c / float(f))
        return best

    def cls_rep_of(w):
        cc = cls_counts.get(w)
        f = freq.get(w, 0)
        return (max(cc.values()) / float(max(f, 1))) if cc else 0.0

    def english_quality_ok(w):
        return (freq.get(w, 0) >= args.en_min_freq
                or cls_rep_of(w) >= args.en_min_cls_rep
                or len(w) >= args.en_min_len)

    def english_gate_ok(w):
        return english_quality_ok(w)

    a_keep = set()
    dropped_a_zero = 0
    dropped_a_embedded = 0
    for w in a_set:
        if freq.get(w, 0) <= 0:
            dropped_a_zero += 1
            continue
        if CJK_RE.search(w) and len(w) >= 2 and containment_ratio(w) >= 0.9:
            dropped_a_embedded += 1
            continue
        a_keep.add(w)

    # R2-A F2 修复后的包含率诊断（写进 build report，用于回归核对 ≤1.0）
    ratio_max = 0.0
    ratio_gt1 = 0
    ratio_ge09 = 0
    for w in a_set:
        if freq.get(w, 0) <= 0:
            continue
        r = containment_ratio(w)
        ratio_max = max(ratio_max, r)
        if r > 1.0:
            ratio_gt1 += 1
        if r >= 0.9:
            ratio_ge09 += 1

    # B 源准入：中文= A/学科词表 或 (df>=min_df_cjk 且 长词包含率<0.9)；英文=质量闸门
    accepted_b = set()
    dropped_b_cjk = 0
    dropped_b_cjk_df_max = 0
    dropped_b_en_quality = 0
    dropped_b_cjk_contained = 0
    for w in b_keep:
        if not (term_ok_kw(w) and not is_stop(w)):
            continue
        if CJK_RE.search(w):
            if w in a_keep or w in sub_lex:
                accepted_b.add(w)
                continue
            if (len(w) >= 2 and b_df[w] >= args.min_df_cjk
                    and containment_ratio(w) < 0.9):
                accepted_b.add(w)
                continue
            if b_df[w] >= args.min_df_cjk:
                dropped_b_cjk_contained += 1
            dropped_b_cjk += 1
            dropped_b_cjk_df_max = max(dropped_b_cjk_df_max, b_df[w])
        else:
            if b_df[w] >= args.min_df and english_gate_ok(w):
                accepted_b.add(w)
            else:
                dropped_b_en_quality += 1

    all_keys = set(a_keep) | accepted_b | c_keys
    rep_map = {}
    ncl_map = {}
    cls_rep_map = {}
    entries = []
    for w in all_keys:
        is_cls = w in c_keys and term_ok_cls(w)
        if not is_cls and (not term_ok_kw(w) or is_stop(w)):
            continue
        if not is_cls and not CJK_RE.search(w) and not english_gate_ok(w):
            continue
        cid = mode_cluster(w)
        rep = representativeness(w)
        f = freq.get(w, 0)
        rep_map[w] = rep
        ncl_map[w] = len(cl_counts.get(w, {}))
        _cc = cls_counts.get(w)
        cls_rep_map[w] = (max(_cc.values()) / float(max(f, 1))) if _cc else 0.0
        if is_cls:
            cls_v = w
        else:
            cc = cls_counts.get(w)
            cls_v = max(cc.items(), key=lambda kv: (kv[1], kv[0]))[0] if cc else ""
            if not cls_v:
                cls_v = fallback_cls_for_cluster(cid)
        sources = [name for bit, name in ((1, "A"), (2, "B"), (4, "C")) if src_mask.get(w, 0) & bit]
        if not sources:
            sources = ["A"] if w in a_keep else (["B"] if w in accepted_b else ["C"])
        # R2-A 修复 F1/F1b：截断排序键取「freq × rep」的**精确值**。
        #   freq × (max(cl_counts)/freq) ≡ max(cl_counts)（freq 被约掉，语义上即"主导簇卡数"）；
        #   原实现按 IEEE754 乘除链计算，结果与 max_cc 可差 1 ulp：184 个节点 score≠max_cc，
        #   同分组的 (-freq, term) 次级键被浮点噪声压制（62 处相邻违例），1 ulp 噪声还决定了
        #   --max-nodes 的截断边界（audit/p1/REPORT.md F1/F1b）。此处按整数精确求值，
        #   排序键语义仍是"频次×簇内代表性"，而 (-freq, term) 次级键恢复生效。
        _cc_cl = cl_counts.get(w)
        score = float(max(_cc_cl.values())) if _cc_cl else f * rep
        entries.append({
            "term": w,
            "type": "cls" if is_cls else "kw",
            "freq": int(f),
            "cluster": int(cid),
            "cls": cls_v,
            "sources": sources,
            "_score": float(score),
        })

    if len(entries) > args.max_nodes:
        entries.sort(key=lambda e: (-e["_score"], -e["freq"], e["term"]))
        entries = entries[:args.max_nodes]
        truncated = True
    else:
        entries.sort(key=lambda e: (-e["_score"], -e["freq"], e["term"]))
        truncated = False
    n = len(entries)
    for i, e in enumerate(entries):
        e["id"] = i
        e.pop("_score", None)
        entries[i] = {k: e[k] for k in ("id", "term", "type", "freq", "cluster", "cls", "sources")}

    if n < args.min_nodes:
        print(f"[WARN] nodes={n:,} < min_nodes={args.min_nodes}; 需要降低 --min-df 重跑", flush=True)
    if n > args.max_nodes:
        print(f"[WARN] nodes={n:,} > max_nodes={args.max_nodes}; 已截断", flush=True)

    nodes_path = os.path.join(out_dir, "nodes.json")
    with open(nodes_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)

    type_counts = Counter(e["type"] for e in entries)
    src_counts = Counter("+".join(e["sources"]) for e in entries)
    freq_values = np.array([e["freq"] for e in entries], dtype=np.int64)
    freq_stats = {
        "min": int(freq_values.min()) if n else 0,
        "p25": int(np.percentile(freq_values, 25)) if n else 0,
        "median": int(np.median(freq_values)) if n else 0,
        "p75": int(np.percentile(freq_values, 75)) if n else 0,
        "p90": int(np.percentile(freq_values, 90)) if n else 0,
        "max": int(freq_values.max()) if n else 0,
        "zero_freq": int((freq_values == 0).sum()) if n else 0,
    }
    report = {
        "stage": "P1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "data_dir": D,
        "out_dir": out_dir,
        "seconds": round(time.time() - t0, 1),
        "r2a_fixes": [
            "F2/F2b：长词包含率证据 ext_df 改为按卡片去重（A 源扩展与 B-CJK 扩展合并为同一趟、"
            "共用 ext_seen）；修复前同一卡同一扩展词被两趟各 +1，比可 >1.0 并误剔 129 个 A 源词",
            "F1/F1b：截断排序键 _score 改为 freq×rep 的精确整数值（≡ 主导簇卡数），"
            "消除 1 ulp 浮点噪声对 (-freq, term) 次级键与截断边界的支配",
        ],
        "params": {
            "top_per_card": args.top_per_card,
            "min_df": args.min_df,
            "min_df_cjk": args.min_df_cjk,
            "en_gate": {"min_freq": args.en_min_freq,
                        "min_cls_rep": args.en_min_cls_rep,
                        "min_len": args.en_min_len},
            "max_nodes": args.max_nodes,
            "min_nodes": args.min_nodes,
            "b_word_mode": "top-title-tokens + build_graph.merge_bigrams(max_len=5,min_ratio=0.25)",
            "b_cjk_policy": "B-only CJK 需在 A 词表或学科词表内；否则剔除",
            "normalization": "NFKC + 去空白 + 长度1-16 + ASCII 小写 + 停用词表",
            "a_fragment_filter": "A 源 CJK 词长词包含率>=0.9 判为碎片剔除",
            "stopword_count": len(STOPWORDS),
            "stopwords": sorted(STOPWORDS),
        },
        "counts": {
            "nodes": n,
            "kw": type_counts.get("kw", 0),
            "cls": type_counts.get("cls", 0),
            "sources": dict(src_counts),
            "source_a_kept": len(a_keep),
            "source_a_dropped_zero_freq": dropped_a_zero,
            "source_a_dropped_embedded": dropped_a_embedded,
            "source_a_raw_unique": a_raw,
            "a_containment_ratio_max": round(ratio_max, 4),
            "a_terms_ratio_gt1": ratio_gt1,
            "a_terms_ratio_ge_0.9": ratio_ge09,
            "source_b_merged_unique": len(b_df),
            "source_b_df5": b_df5,
            "source_b_df8": b_df8,
            "source_b_df10": b_df10,
            "source_b_kept": len(b_keep),
            "source_b_accepted": len(accepted_b),
            "source_b_dropped_cjk": dropped_b_cjk,
            "source_b_dropped_cjk_contained": dropped_b_cjk_contained,
            "source_b_dropped_cjk_max_df": dropped_b_cjk_df_max,
            "source_b_dropped_en_quality": dropped_b_en_quality,
            "source_c": len(c_keys),
            "truncated": truncated,
        },
        "freq_stats": freq_stats,
        "nodes_path": nodes_path,
    }
    report_path = args.report or os.path.join(out_dir, "p1-build-report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # ---- 50 词分层抽样候选（判定留待人工/复审步骤） ----
    if args.sample_out:
        rng = np.random.default_rng(args.seed)
        asc = sorted(entries, key=lambda e: -e["freq"])
        n_total = len(asc)
        _k_high = max(1, round(args.sample_size * 0.34))
        _k_mid = max(1, round(args.sample_size * 0.34))
        _k_low = max(1, args.sample_size - _k_high - _k_mid)
        tiers = [
            ("high", asc[: max(1, n_total // 3)], _k_high),
            ("mid", asc[n_total // 3: max(n_total // 3 + 1, 2 * n_total // 3)], _k_mid),
            ("low", asc[max(n_total // 3 + 1, 2 * n_total // 3):], _k_low),
        ]
        rows = []
        for name, pool, k in tiers:
            k = min(k, len(pool))
            idxs = rng.choice(len(pool), size=k, replace=False)
            for j in sorted(idxs, key=lambda x: -pool[x]["freq"]):
                e = pool[j]
                rows.append((name, e))
        sample_path = os.path.abspath(os.path.expanduser(args.sample_out))
        with open(sample_path, "w", encoding="utf-8") as f:
            f.write("# P1 分层抽样候选（stratum\tid\tterm\ttype\tfreq\tcluster\tcls\tcls_rep\tsources\trep\tn_clusters\tverdict\treason）\n")
            for name, e in rows:
                f.write(f"{name}\t{e['id']}\t{e['term']}\t{e['type']}\t{e['freq']}\t"
                        f"{e['cluster']}\t{e['cls']}\t{cls_rep_map.get(e['term'], 0.0):.3f}\t"
                        f"{'+'.join(e['sources'])}\t{rep_map.get(e['term'], 0.0):.3f}\t"
                        f"{ncl_map.get(e['term'], 0)}\t\t\n")
        print(f"[sample] {len(rows)} candidates -> {sample_path}", flush=True)

    print(f"[done] nodes={n:,} (kw={type_counts.get('kw',0):,} cls={type_counts.get('cls',0):,}) "
          f"truncated={truncated} -> {nodes_path} | {time.time()-t0:.1f}s", flush=True)
    print(f"[report] {report_path}", flush=True)

    if n < args.min_nodes or n > args.max_nodes:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

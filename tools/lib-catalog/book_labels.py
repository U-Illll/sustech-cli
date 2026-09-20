#!/usr/bin/env python3
"""书标编号查询层（labels.db）——检索输出接入（2026-09-20）

作用：mms → 位置 + 书标编号（call_number_pure），为检索工具提供「图书馆+书架+编号」字段。
数据：~/go/lib-catalog-data/labels.db（由 build_labels_db.py 从 catalog_labeled.csv 构建）。
用法（其他脚本）：
    import book_labels as BL
    labs = BL.query_labels(D, mms_list)          # {mms: [(lib, sub, shelf, call), ...]}
    loc_disp, call_disp = BL.brief(labs.get(mms, []))   # 概览字符串
"""
import os, re, sqlite3

# 馆藏地短化表（与 booklist_gen.clean_loc 同口径）
_SUB_MAP = {
    '1st Floor Compact Book Shelves': '1F·Compact',
    '2nd Floor Reading Space': '2F·阅读空间',
    '3rd Floor Reading Space': '3F·阅读空间',
    '4th Floor Reading Space': '4F·阅读空间',
    '1st Floor Foreign Language Fictions': '1F·外文小说区',
    '1st Floor Reference': '1F·参考区',
    '4th Floor Thematic Bookshelf_Yidan': '4F·主题书架',
    '2nd Floor Newspapers/Periodicals Area': '2F·报刊区',
    '1st Floor New Arrival': '1F·新书区',
    '1st Floor English Classics': '1F·英文经典',
    '1st Floor Graded Readers': '1F·分级读物',
    '1st Floor Scholar Recommend Shelf': '1F·学者推荐架',
}
_LIB_MAP = {'一丹图书馆': '一丹馆', '琳恩图书馆': '琳恩馆', '涵泳图书馆': '涵泳馆', 'library': 'library'}


def db_path(D):
    return os.path.join(D, "labels.db")


def _natkey(s):
    key = []
    for p in re.split(r'(\d+)', s or ''):
        if not p:
            continue
        if p.isdigit():
            key.append((0, int(p)))
        else:
            key.append((1, p))
    return tuple(key)


def loc_brief(lib, sub, shelf):
    """位置短形式：'一丹馆 1F·Compact 第32排A面'"""
    lib = _LIB_MAP.get((lib or '').strip(), (lib or '').strip())
    sub = (sub or '').strip()
    sub = _SUB_MAP.get(sub, re.sub(r'(\d)(?:st|nd|rd|th) Floor\b', r'\1F', sub))
    shelf = (shelf or '').strip()
    return " ".join(p for p in (lib, sub, shelf) if p)


def query_labels(D, mms_list):
    """批量查询：{mms: [(lib, sub, shelf, call), ...]}（组内按源序 seq；无记录的 mms 不在返回中）"""
    mmsu = list(dict.fromkeys(m for m in mms_list if m))
    if not mmsu:
        return {}
    p = db_path(D)
    if not os.path.exists(p):
        return {}
    out = {}
    con = sqlite3.connect(p)
    try:
        for i in range(0, len(mmsu), 500):
            chunk = mmsu[i:i + 500]
            q = ",".join("?" * len(chunk))
            for mms, _seq, lib, sub, shelf, call in con.execute(
                    f"SELECT mms, seq, lib, sub, shelf, call FROM label WHERE mms IN ({q}) ORDER BY seq", chunk):
                out.setdefault(mms, []).append((lib, sub, shelf, call))
    finally:
        con.close()
    return out


def brief(entries):
    """entries: [(lib, sub, shelf, call), ...] → (loc_display, call_display)

    规则：编号去重+自然序；多编号 → '首个 等N个'；
        位置：以「首个有编号的对」为锚（无编号书取首位置）；多位置 → ' 等N处'。
    """
    if not entries:
        return "", ""
    calls = sorted({c for (_l, _s, _k, c) in entries if (c or '').strip()}, key=_natkey)
    locs_seen = []
    for e in entries:
        key = (e[0], e[1], e[2])
        if key not in locs_seen:
            locs_seen.append(key)
    anchor = next((e for e in entries if (e[3] or '').strip()), None)
    if anchor is not None:
        loc_disp = loc_brief(anchor[0], anchor[1], anchor[2])
    else:
        loc_disp = loc_brief(entries[0][0], entries[0][1], entries[0][2])
    if loc_disp and len(locs_seen) > 1:
        loc_disp += f" 等{len(locs_seen)}处"
    call_disp = ""
    if calls:
        call_disp = calls[0] + (f" 等{len(calls)}个" if len(calls) > 1 else "")
    return loc_disp, call_disp


def all_calls(D):
    """全量 {mms: call_display}（booklist 全量场景用）"""
    p = db_path(D)
    if not os.path.exists(p):
        return {}
    con = sqlite3.connect(p)
    out = {}
    try:
        gather = {}
        for mms, call in con.execute("SELECT mms, call FROM label ORDER BY mms, seq"):
            if (call or '').strip():
                gather.setdefault(mms, []).append(call.strip())
        for mms, calls in gather.items():
            calls = sorted(set(calls), key=_natkey)
            out[mms] = calls[0] + (f" 等{len(calls)}个" if len(calls) > 1 else "")
    finally:
        con.close()
    return out

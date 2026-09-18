#!/usr/bin/env python3
"""F17(i): is the discarded hits.sort(-w,-match,id) ever observable? (proof + real-query scan)"""
import importlib.util, math, random
spec=importlib.util.spec_from_file_location("tg","/home/wzh/go/lib-catalog-data/topics/audit/graph/topic_graph.audited.py")
tg=importlib.util.module_from_spec(spec); spec.loader.exec_module(tg)
D="/home/wzh/go/lib-catalog-data"; nodes,_=tg.load_nodes(D)
def hits(q):
    qn=tg.normalize_term(q); qt=[tg.normalize_term(t) for t in tg.tokenize(q)]; h=[]
    for n in nodes:
        m=tg.match_score(n["term"],qn,qt)
        if m>0: h.append({"id":n["id"],"match":round(m,3),"w":round(m*math.log1p(max(int(n["freq"]),0)),4)})
    return h
random.seed(0); found=0
for q in [n["term"][:k] for n in random.sample(nodes,400) for k in (2,3)]:
    h=hits(q)
    if len(h)>1 and [x["id"] for x in sorted(h,key=lambda x:(-x["w"],-x["match"],x["id"]))] != [x["id"] for x in sorted(h,key=lambda x:(-x["w"],x["id"]))]:
        found+=1
print("real-data queries (800 sampled prefixes) where the two keys disagree:",found)

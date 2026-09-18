#!/usr/bin/env python3
"""F11: displayed w-order of expanded_hits vs the agg ranking key the run actually used."""
import importlib.util, math
spec=importlib.util.spec_from_file_location("tg","/home/wzh/go/lib-catalog-data/topics/audit/graph/topic_graph.audited.py")
tg=importlib.util.module_from_spec(spec); spec.loader.exec_module(tg)
D="/home/wzh/go/lib-catalog-data"; nodes,_=tg.load_nodes(D)
mms,tc,fwd=tg.load_card_topics(D,need_mms=True,need_forward=True)
W=lambda e: e["rel"]*math.log1p(max(int(nodes[e["id"]]["freq"]),1))
for q in ("接口技","量子","风险管"):
    exp,_=tg.tfidf_expand(D,q,mms,fwd,nodes,top_cards=50,top_topics=10,rank_by="agg")
    d=sorted(exp,key=lambda e:(-W(e),e["id"]))
    print(q," rank_key=agg order:",[(e["id"],nodes[e["id"]]["term"],round(e["agg"],3)) for e in exp])
    print(" "*len(q)," displayed(w)  order:",[(e["id"],nodes[e["id"]]["term"],round(e["agg"],3)) for e in d],
          " agg-monotone?",all(d[i]["agg"]>=d[i+1]["agg"] for i in range(len(d)-1)))

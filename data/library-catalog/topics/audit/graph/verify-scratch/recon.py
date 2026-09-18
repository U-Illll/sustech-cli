import json, os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np
D="/home/wzh/go/lib-catalog-data"
nodes=json.load(open(os.path.join(D,"topics/nodes.json"),encoding="utf-8"))
print("nodes:",len(nodes))
ids=[n["id"] for n in nodes]
print("ids==range?", ids==list(range(len(nodes))))
print("keys:", sorted(nodes[0].keys()))
z=np.load(os.path.join(D,"topics/edges.csr.npz"))
ip,ix,wt=z["indptr"],z["indices"],z["weights"]
print("indptr",ip.shape,ip.dtype,"indices",ix.shape,ix.dtype,"weights",wt.shape,wt.dtype)
print("indptr len == len(nodes)+1 ?", len(ip)==len(nodes)+1, len(ip))
print("max index:",int(ix.max()),"min:",int(ix.min()))
print("weight min/max:",float(wt.min()),float(wt.max()),"nan?",bool(np.isnan(wt).any()),"zero count:",int((wt==0).sum()))
import collections
c=collections.Counter()
with open(os.path.join(D,"topics/card_topics.jsonl"),encoding="utf-8") as f:
    n=0;blank=0;maxt=-1
    for line in f:
        if not line.strip(): blank+=1; continue
        o=json.loads(line); n+=1
        for t in o.get("topics",()):
            maxt=max(maxt,int(t))
print("card_topics records:",n,"blank:",blank,"max topic id:",maxt, ">= nodes?", maxt>=len(nodes))
with open(os.path.join(D,"cards.jsonl"),encoding="utf-8") as f:
    cl=sum(1 for _ in f)
print("cards.jsonl lines:",cl)

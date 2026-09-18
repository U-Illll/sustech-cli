"""Build tiny fixture data dirs in scratch: mkfix.py <name> <spec.json-ish via code>"""
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np

def csr(n_nodes, edges, dtype_ok=True):
    # edges: list of (u,v,w)
    ip=[0]*(n_nodes+1)
    for u,_,_ in edges: ip[u+1]+=1
    for i in range(n_nodes): ip[i+1]+=ip[i]
    cur=ip[:]
    ix=[0]*len(edges); wt=[0.0]*len(edges)
    for u,v,w in edges:
        p=cur[u]; ix[p]=v; wt[p]=w; cur[u]=p+1
    return np.array(ip,dtype=np.int64), np.array(ix,dtype=np.int32), np.array(wt,dtype=np.float32)

def write(name, nodes, edges, card_topics, cards=None, indptr=None, indices=None, weights=None, nodes_raw=None):
    d=os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    os.makedirs(os.path.join(d,"topics"), exist_ok=True)
    os.makedirs(os.path.join(d,"index"), exist_ok=True)
    with open(os.path.join(d,"topics/nodes.json"),"w",encoding="utf-8") as f:
        json.dump(nodes_raw if nodes_raw is not None else nodes, f, ensure_ascii=False)
    ip,ix,wt = csr(len(nodes), edges)
    if indptr is not None: ip = indptr
    if indices is not None: ix = indices
    if weights is not None: wt = weights
    np.savez(os.path.join(d,"topics/edges.csr.npz"), indptr=ip, indices=ix, weights=wt)
    with open(os.path.join(d,"topics/card_topics.jsonl"),"w",encoding="utf-8") as f:
        for o in card_topics: f.write(json.dumps(o,ensure_ascii=False)+"\n")
    if cards is not None:
        with open(os.path.join(d,"cards.jsonl"),"w",encoding="utf-8") as f:
            for c in cards: f.write(json.dumps(c,ensure_ascii=False)+"\n")
    return d

def N(i,term,freq=10,**kw):
    n={"id":i,"term":term,"type":"kw","freq":freq,"cluster":-1,"cls":"","sources":{"kw":1}}
    n.update(kw); return n

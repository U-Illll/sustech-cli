import importlib.util, json, os, sys, math
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np
spec=importlib.util.spec_from_file_location("tg","/home/wzh/go/lib-catalog-data/topics/audit/graph/topic_graph.audited.py")
tg=importlib.util.module_from_spec(spec); spec.loader.exec_module(tg)
D="/home/wzh/go/lib-catalog-data"
nodes,_=tg.load_nodes(D); ip,ix,wt=tg.load_edges(D); N=len(nodes)

print("### F3 direct-call guards")
for kw in [dict(decay=0.0),dict(decay=-0.5),dict(decay=1.1),dict(decay=2.0),dict(hops=0),dict(hops=70),
           dict(budget=0),dict(budget=-3),dict(threshold=2.0),dict(threshold=-1.0)]:
    a=dict(seed=139,hops=2,indptr=ip,indices=ix,weights=wt,decay=0.86,threshold=0.05,budget=50000)
    a.update(kw)
    try:
        r=tg.diffuse(**a)
        sc=r["score"]; mx=max(sc.values()) if sc else None
        print(f"  {kw} -> no error; visited={r['visited']} maxscore={mx} saturated={r['saturated']}")
    except Exception as e:
        print(f"  {kw} -> {type(e).__name__}: {e}")

print("### F3 decay>1 -> score>1 (direct call on real graph)")
r=tg.diffuse(139,2,ip,ix,wt,1.1,0.05,50000)
print("  decay=1.1 max score:",round(max(r['score'].values()),4),"(>1)")

print("### F3 path_len guard=64 (direct call, real graph, hops=70)")
r=tg.diffuse(139,70,ip,ix,wt,0.86,0.05,50000)
lay=r["layer"]; bad=[i for i in lay if tg.path_len(i,r)!=lay[i]]
print("  visited",r["visited"],"max layer",max(lay.values()),"nodes where len(parent-chain)!=layer:",len(bad),bad[:5])
if bad:
    i=bad[0]; print("  example id",i,"layer",lay[i],"path_len",tg.path_len(i,r),"chain-walk-to-root:",
                    tg.path_len(i,r,max_hops=1000))
print("  path_of(nid,...,max_hops=hops+1) uses limit",70+1,"-> not truncated")

print("### F4 exact-length-walk DP upper bound vs diffuse (seed 139, decay .86, thr .05)")
src=ix.astype(np.int64); dst=ix.astype(np.int64)  # placeholder
# build edge list u->v
eu=np.repeat(np.arange(N,dtype=np.int64), np.diff(ip))
ev=src.copy(); ew=wt.astype(np.float64)
order=np.argsort(eu,kind="stable"); eu,ev,ew=eu[order],ev[order],ew[order]
for hops in (2,3,12):
    reg=tg.diffuse(139,hops,ip,ix,wt,0.86,0.05,50000)
    score=reg["score"]
    Dprev={139:1.0}; par={}; best={139:1.0}; bestl={139:0}
    Dcur={}; parcur={}
    for L in range(1,hops+1):
        Dcur={}; parcur={}
        for u,v,w in zip(eu,ev,ew):
            su=Dprev.get(u)
            if su is None: continue
            s=su*w*0.86
            if s>=0.05 and (v not in Dcur):
                pass
            cur=Dcur.get(v)
            if cur is None or s>cur:
                Dcur[v]=s; parcur[v]=u
        par[L]=parcur
        for v,s in Dcur.items():
            if s>best.get(v,-1.0): best[v]=s; bestl[v]=L
        Dprev=Dcur
    under=[(v,score[v],best[v],reg["layer"].get(v),bestl[v]) for v in score if score[v]+1e-6*max(1,abs(best.get(v,0)))<best.get(v,0)]
    def simple(v,L):
        seen=set(); cur=v; l=L
        while l>0:
            if cur in seen: return False
            seen.add(cur); cur=par.get(l,{}).get(cur)
            if cur is None: return False
            l-=1
        return cur not in seen
    n_simple=sum(1 for v,sc,b,ly,bl in under if simple(v,bl))
    missing=[v for v,b in best.items() if b>=0.05 and v not in score]
    print(f"  hops={hops}: region={reg['visited']} under-scored={len(under)} (of which walk-is-simple-path={n_simple}) best-reachable-missing={len(missing)}")
    if under:
        ex=sorted(under,key=lambda t:-(t[2]-t[1]))[:3]
        print("    worst examples (id, diffuse_score, best<=hops, diffuse_layer, best_len):")
        for e in ex: print("      ",e[0],nodes[e[0]]['term'],round(e[1],4),round(e[2],4),e[3],e[4])

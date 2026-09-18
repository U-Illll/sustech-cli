import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mkfix import write, N, csr
import numpy as np
S=os.path.dirname(os.path.abspath(__file__))
def d(n): return os.path.join(S,n)

# --- f1a: index >= len(nodes)
write("fx_f1a",[N(0,"a"),N(1,"b"),N(2,"c")],[(0,5,1.0)],[{"mms":"M0","topics":[0]}],[{"title":"A","mms":"MA"}])
# --- f1b: truncated indptr (len 2, should be 4); seed 1 is last index
write("fx_f1b",[N(0,"a"),N(1,"b"),N(2,"c")],[(1,0,1.0)],[{"mms":"M0","topics":[0]}],[{"title":"A","mms":"MA"}],
      indptr=np.array([0,1],dtype=np.int64))
# --- f1d: nodes.json missing "cls"
nodes_d=[N(0,"机器",817),N(1,"学习",1239)]
for n in nodes_d: n.pop("cls")
write("fx_f1d",nodes_d,[(0,1,0.5)],[{"mms":"M0","topics":[0]}],[{"title":"A","mms":"MA"}])
# --- f1e: list order != id
write("fx_f1e",[N(2,"ccc"),N(0,"aaa"),N(1,"bbb")],[(0,1,0.5),(1,2,0.5)],[{"mms":"M0","topics":[0]}],[{"title":"A","mms":"MA"}])
# --- f1f: NaN edge weight
write("fx_nan",[N(0,"a"),N(1,"b")],[(0,1,float("nan"))],[{"mms":"M0","topics":[0]}],[{"title":"A","mms":"MA"}])
# --- f7a: cards.jsonl absent
write("fx_f7a",[N(0,"a"),N(1,"b")],[(0,1,0.9)],[{"mms":"M0","topics":[0,1]}],cards=None)
# --- f7b: blank line in cards.jsonl at a wanted index
write("fx_f7b",[N(0,"a"),N(1,"b")],[(0,1,0.9)],[{"mms":"M0","topics":[0,1]}],[{"title":"A","mms":"MA"}])
with open(d("fx_f7b")+"/cards.jsonl","w",encoding="utf-8") as f:
    f.write("\n"); f.write(json.dumps({"title":"A","mms":"MA"},ensure_ascii=False)+"\n")
# --- f8: card_topics record missing at the FRONT (2 cards, 1 record)
write("fx_f8",[N(0,"a"),N(1,"b")],[(0,1,0.9)],[{"mms":"MB","topics":[0]}],
      [{"title":"A","mms":"MA"},{"title":"B","mms":"MB"}])
# --- f8b: blank line inside card_topics
write("fx_f8b",[N(0,"a"),N(1,"b")],[(0,1,0.9)],[{"mms":"M1","topics":[0,1]},{"mms":"M2","topics":[1]}],
      [{"title":"A","mms":"M1"},{"title":"B","mms":"M2"}])
p=d("fx_f8b")+"/topics/card_topics.jsonl"
body=open(p,encoding="utf-8").read()
open(p,"w",encoding="utf-8").write("\n"+body)
# --- f12: zero-weight edge, threshold 0
write("fx_f12",[N(0,"a"),N(1,"b"),N(2,"c")],[(0,1,0.0),(0,2,0.5)],
      [{"mms":"M1","topics":[1]},{"mms":"M0","topics":[0]}],[{"title":"B","mms":"M1"},{"title":"A","mms":"M0"}])
print("built", sorted(x for x in os.listdir(S) if x.startswith("fx_")))

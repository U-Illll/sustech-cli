#!/usr/bin/env node
/**
 * node-client.js — lib-catalog 数据集 Node.js 参考客户端（零依赖）
 *
 * 用法:
 *   node node-client.js <dataDir> search "<query>" [--top 10]   # 元数据 + TF-IDF 打分
 *   node node-client.js <dataDir> similar <mms> [--top 10]      # 语义检索演示（int8 管线）
 *   node node-client.js <dataDir> links <mms> [--top 10]        # 语义内链（图，预计算）
 *   node node-client.js <dataDir> cluster <mms|#id>             # 语义簇信息
 *   node node-client.js <dataDir> docid <mms>                   # Primo docId / detailUrl
 *
 * 语义检索接入说明（真实场景）:
 *   1) 查询文本 → bge-small-zh-v1.5 编码 → 512 维向量 → L2 归一化
 *   2) 若存在 pca_components.f32.bin: q = normalize(q @ W.T)   （512→384）
 *   3) 与 embeddings_int8 点积: score[i] = Σ q8[i][j]*q[j] * scale[i]/127
 *   4) 排序取 top-K（本文件中 semSearch 即为该流程，similar 命令用库内向量模拟查询）
 */
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

// ---------- 分词（与 catalog_vector.py 同源） ----------
const LATIN = /[a-z0-9][a-z0-9_.\-]*/g;
const CJK = /[\u4e00-\u9fff]/;
function bigramOf(seg, out) {
  if (seg.length >= 2) for (let i = 0; i < seg.length - 1; i++) out.push(seg.slice(i, i + 2));
  else if (seg.length === 1) out.push(seg);
}
function cjkBigrams(text, out) {
  let seg = "";
  for (const ch of text) {
    if (CJK.test(ch)) seg += ch;
    else { if (seg) bigramOf(seg, out); seg = ""; }
  }
  if (seg) bigramOf(seg, out);
}
function tokenize(text) {
  const out = [];
  const low = text.toLowerCase();
  let last = 0, m;
  LATIN.lastIndex = 0;
  while ((m = LATIN.exec(low)) !== null) {
    cjkBigrams(low.slice(last, m.index), out);
    out.push(m[0]);
    last = m.index + m[0].length;
  }
  cjkBigrams(low.slice(last), out);
  return out;
}

// ---------- 数据加载 ----------
function loadJson(p) { return JSON.parse(fs.readFileSync(p, "utf8")); }

class Catalog {
  constructor(dir) {
    this.dir = dir;
    const t0 = Date.now();
    const gz = zlib.gunzipSync(fs.readFileSync(path.join(dir, "cards.jsonl.gz")));
    this.cards = [];
    for (const ln of gz.toString("utf8").split("\n")) if (ln) this.cards.push(JSON.parse(ln));
    this.N = this.cards.length;
    // tfidf
    const tf = path.join(dir, "tfidf");
    this.vocab = loadJson(path.join(tf, "vocab.json"));
    this.vocabMap = new Map();
    this.vocab.forEach((t, i) => this.vocabMap.set(t, i));
    this.idf = new Float32Array(fs.readFileSync(path.join(tf, "idf.f32.bin")).buffer);
    this.Xindptr = new Int32Array(fs.readFileSync(path.join(tf, "indptr.bin")).buffer);
    this.Xindices = new Int32Array(fs.readFileSync(path.join(tf, "indices.bin")).buffer);
    this.Xdata = new Float32Array(fs.readFileSync(path.join(tf, "data.f32.bin")).buffer);
    // knn（int32 行偏移）
    this.indptr = new Int32Array(fs.readFileSync(path.join(dir, "knn_indptr.i32.bin")).buffer);
    this.knnIdx = new Int32Array(fs.readFileSync(path.join(dir, "knn_indices.i32.bin")).buffer);
    this.knnSims = new Uint8Array(fs.readFileSync(path.join(dir, "knn_sims.u8.bin")).buffer);
    // clusters
    this.labels = new Int32Array(fs.readFileSync(path.join(dir, "clusters.i32.bin")).buffer);
    this.clustersDoc = loadJson(path.join(dir, "clusters.json")).clusters;
    // embeddings（int8；可选 PCA）
    this.embQ = new Int8Array(fs.readFileSync(path.join(dir, "embeddings_int8.bin")).buffer);
    this.embScale = new Float32Array(fs.readFileSync(path.join(dir, "embeddings_scale.f32.bin")).buffer);
    this.dim = this.embQ.length / this.N;
    const pcaP = path.join(dir, "pca_components.f32.bin");
    this.pca = null;
    if (fs.existsSync(pcaP)) {
      const buf = fs.readFileSync(pcaP);
      this.pca = new Float32Array(buf.buffer);
      this.pcaDim = buf.length / 4 / 512;
    }
    this.mmsIndex = new Map();
    this.cards.forEach((c, i) => this.mmsIndex.set(c.mms, i));
    this.loadMs = Date.now() - t0;
  }

  /** 512→dim 投影 + L2 归一化（若数据为 PCA 版） */
  prepareQuery(vec) {
    let q = vec;
    if (this.pca && vec.length === 512) {
      const out = new Float32Array(this.pcaDim);
      for (let j = 0; j < this.pcaDim; j++) {
        let s = 0;
        const base = j * 512;
        for (let k = 0; k < 512; k++) s += vec[k] * this.pca[base + k];
        out[j] = s;
      }
      q = out;
    }
    let n = 0;
    for (let i = 0; i < q.length; i++) n += q[i] * q[i];
    n = Math.sqrt(n) || 1;
    const nq = new Float32Array(q.length);
    for (let i = 0; i < q.length; i++) nq[i] = q[i] / n;
    return nq;
  }

  /** 语义检索：queryVec（512 维原始归一化向量）→ top-K */
  semSearch(queryVec, topN = 10) {
    const q = this.prepareQuery(queryVec);
    const D = q.length;
    const scores = new Float32Array(this.N);
    const { embQ, embScale } = this;
    for (let i = 0; i < this.N; i++) {
      let dot = 0;
      const base = i * D;
      for (let j = 0; j < D; j++) dot += embQ[base + j] * q[j];
      scores[i] = dot * embScale[i] / 127;
    }
    return topK(scores, topN);
  }

  /** TF-IDF 关键词搜索 */
  kwSearch(query, topN = 10) {
    const terms = tokenize(query).filter(t => this.vocabMap.has(t));
    if (!terms.length) return [];
    const q = new Float32Array(this.vocab.length);
    for (const t of terms) q[this.vocabMap.get(t)] += this.idf[this.vocabMap.get(t)];
    let norm = 0; for (let i = 0; i < q.length; i++) norm += q[i] * q[i];
    norm = Math.sqrt(norm); if (norm > 0) for (let i = 0; i < q.length; i++) q[i] /= norm;
    const score = new Float32Array(this.N);
    const { Xindptr, Xindices, Xdata } = this;
    for (let d = 0; d < this.N; d++) {
      let s = 0;
      for (let k = Xindptr[d]; k < Xindptr[d + 1]; k++) {
        const qv = q[Xindices[k]];
        if (qv !== 0) s += Xdata[k] * qv;
      }
      if (s > 0) score[d] = s;
    }
    return topK(score, topN);
  }

  /** 库内向量（反量化）作为查询的语义检索（演示/验证用） */
  similarByRow(i, topN = 10) {
    const D = this.dim, base = i * D;
    const qv = new Float32Array(512).fill(0);      // 占位：本函数直接走 int8 空间
    return this.semSearchInt8Row(i, topN);
  }

  semSearchInt8Row(i, topN = 10) {
    const D = this.dim, base = i * D, sc = this.embScale[i] / 127;
    const scores = new Float32Array(this.N);
    const { embQ } = this;
    for (let r = 0; r < this.N; r++) {
      let dot = 0;
      const b2 = r * D;
      for (let j = 0; j < D; j++) dot += embQ[b2 + j] * embQ[base + j];
      scores[r] = dot * this.embScale[r] / 127 * sc;
    }
    scores[i] = -1;
    return topK(scores, topN);
  }

  links(i, topN = 12) {
    const res = [];
    for (let k = this.indptr[i]; k < this.indptr[i + 1] && res.length < topN; k++) {
      res.push([this.knnIdx[k], this.knnSims[k] / 255]);
    }
    return res;
  }
}

function topK(scores, k) {
  const idx = Array.from(scores.keys());
  idx.sort((a, b) => scores[b] - scores[a]);
  return idx.slice(0, k).map(i => [i, scores[i]]);
}
function fmt(c) {
  const creator = (c.creator || "").split("$$Q")[0].trim().slice(0, 40);
  const cls = c.cls ? `[${c.cls}] ` : "";
  return `${cls}${(c.title || "").slice(0, 60)}  ${creator}  ${c.year || ""}`;
}
function docId(mms) { return `L:alma${mms}`; }
function detailUrl(mms) {
  return `https://sustc.primo.exlibrisgroup.com.cn/discovery/fulldisplay?docid=alma${mms}&context=L&vid=86SUSTC_INST:86SUSTC_INST&lang=zh_CN`;
}

function main() {
  const [dir, cmd, arg, ...rest] = process.argv.slice(2);
  if (!dir || !cmd || !arg) {
    console.error("用法: node node-client.js <dataDir> search|similar|links|cluster|docid <arg> [--top N]");
    process.exit(1);
  }
  const topArg = rest.indexOf("--top");
  const topN = topArg >= 0 ? parseInt(rest[topArg + 1], 10) : 10;
  const cat = new Catalog(dir);
  const pcaInfo = cat.pca ? ` + PCA→${cat.pcaDim}` : "";
  console.log(`[loaded] ${cat.N} cards, dim=${cat.dim}${pcaInfo} in ${cat.loadMs} ms`);

  if (cmd === "search") {
    const hits = cat.kwSearch(arg, topN);
    hits.forEach(([i, s], r) => console.log(` ${r + 1}. ${s.toFixed(3)}  ${fmt(cat.cards[i])}`));
  } else if (cmd === "similar" || cmd === "sem") {
    const i = cat.mmsIndex.get(arg);
    if (i === undefined) { console.error("mms not found"); process.exit(2); }
    console.log(`# ${fmt(cat.cards[i])}`);
    for (const [j, s] of cat.semSearchInt8Row(i, topN)) console.log(`  ${s.toFixed(3)}  ${fmt(cat.cards[j])}`);
  } else if (cmd === "links") {
    const i = cat.mmsIndex.get(arg);
    if (i === undefined) { console.error("mms not found"); process.exit(2); }
    console.log(`# ${fmt(cat.cards[i])}`);
    for (const [j, s] of cat.links(i, topN)) console.log(`  ${s.toFixed(3)}  ${fmt(cat.cards[j])}`);
  } else if (cmd === "cluster") {
    let cl;
    if (arg.startsWith("#")) cl = parseInt(arg.slice(1), 10);
    else {
      const i = cat.mmsIndex.get(arg);
      if (i === undefined) { console.error("mms not found"); process.exit(2); }
      cl = cat.labels[i];
    }
    const d = cat.clustersDoc[cl];
    console.log(`cluster #${d.id} (${d.size} cards)`);
    console.log(`keywords: ${d.keywords.join(" / ")}`);
    console.log(`exemplars: ${d.exemplars.join(", ")}`);
  } else if (cmd === "docid") {
    console.log(docId(arg));
    console.log(detailUrl(arg));
  } else {
    console.error(`unknown cmd: ${cmd}`);
    process.exit(1);
  }
}
main();

# 南科大图书馆目录爬虫工具包（library-crawler）

从南方科技大学图书馆 Primo 公开检索接口抓取**公开书目事实数据**，编译为可离线检索的
`cards.jsonl` / 主题图产物，并提供**增量刷新**能力，供社区定期更新数据。

> **数据来源与合规**：只抓取公开检索结果里的书目事实字段（题名/著者/出版者/年份/语种/索书号/馆藏位置）。
> **不做**任何账号登录、不绕过鉴权、不抓取全文或读者数据。
> 对端站点受**礼貌速率**约束：本包所有脚本默认 ≤5 req/s（实测 5.5 req/s 零错、8.5 req/s 开始 400），
> 请勿调低 `--min-interval`（脚本内置硬下限 0.18s，低于即拒绝启动）。

---

## 1. 脚本清单

| 脚本 | 用途 | 何时用 | 输入 → 输出 |
|---|---|---|---|
| `scrape.py` | **首次全量**抓取器（v9 并发版）：索书号前缀树细分为"叶子"，叶子内多排序并行补齐；断点队列 + 收敛轮 + 缺口登记 | 第一次建库 | Primo REST → `output/records.jsonl`、`output/progress.json`、`output/scrape.log` |
| `recovery_crawl_v3.py` | **遗留缺口补抓**：对 `scrape.py` 登记但未补齐的前缀做递归细分补抓（根级并行 4，共享同一速率限制器） | 全量跑完后仍有缺口 | `output/progress.json` 的 gaps → 追加 `records.jsonl` |
| `process.py` | **记录整理**：按 `mms` 去重合并馆藏 → 导出 CSV / SQLite / 统计报告 | 每次抓取结束后 | `records.jsonl` → `final/{catalog_full.csv, books.csv, shelf_index.csv, sustc_library.db, report.txt}` |
| `refresh_catalog.py` | **增量刷新（本包新增，核心）**：按入藏日期倒序抓新书 → 编译成 `cards.jsonl` 同口径 → 归类到**现有主题节点** → 增量包 + 合并指引；全程断点续传 + 速率安全带 | **日常/每周更新** | Primo REST（或 `--records-from` 离线） → `cards_delta.jsonl`、`card_topics_delta.jsonl`、`manifest.json`、`MERGE.md` |
| `keeper.sh` | 进程看护：引擎意外退出且未完成则自动重启（`setsid` 脱组） | 长跑全量时挂着 | 轮询 `scrape.log` / `pgrep` |
| `watchdog.sh` | 收尾看护：检测全量完成 → 自动跑 `process.py` → 投递交付文件到指定目录 | 无人值守全量 | 轮询日志 → 调 `process.py` |
| `watch_recovery_v3.sh` | 补抓轮看护（同上，针对 `recovery_crawl_v3.py`） | 补抓长跑 | 轮询 |

> 说明：`keeper.sh` / `watchdog.sh` 里的路径（`/tmp/library-scrape`、桌面投递目录）是首次抓取现场的原始值，
> 直接复用请先按自己的目录改；`scrape.py` / `process.py` 也把工作目录写死为 `/tmp/library-scrape`
> （可用 `ln -s` 或改这两处常量适配）。**`refresh_catalog.py` 全部路径走参数**，无需改代码。

---

## 2. 依赖与安装

```bash
python3 -m venv .venv && source .venv/bin/activate     # 可选
pip install -r requirements.txt                        # requests（必需）+ numpy（可选）
```

* `requests`：联网抓取必需。
* `numpy`：仅当 `refresh_catalog.py --idf-from index` 要读 `index/idf.npy` 时需要；
  缺失时自动**回退**为"用 `cards.jsonl` 现算 df"，功能不受影响（日志会标注 `[idf] 来源 cards.jsonl 现算`）。
* Python 3.8+（开发与实测环境为 3.10 / 3.11）。

---

## 3. 快速开始

### 3.1 首次全量（一次性，耗时较长）

```bash
mkdir -p /tmp/library-scrape && cd /tmp/library-scrape
python3 /path/to/library-crawler/scrape.py            # 断点续跑：直接再运行即可
# 长跑建议挂看护（按需修改脚本内路径）
nohup bash /path/to/library-crawler/keeper.sh &
python3 /path/to/library-crawler/recovery_crawl_v3.py # 补齐 scrape.py 登记的缺口
python3 /path/to/library-crawler/process.py           # records.jsonl → CSV/SQLite
```

### 3.2 日常增量（推荐用这个）

```bash
python3 refresh_catalog.py \
  --catalog ~/go/lib-catalog-data \
  --out ~/go/lib-catalog-data/refresh-$(date +%Y%m%d)
# 产物：cards_delta.jsonl / card_topics_delta.jsonl / manifest.json / MERGE.md / state.json
# 按 MERGE.md 合并进现有发行包（追加即可，mms 唯一）
```

离线/演练（不联网，用已抓好的记录）：

```bash
python3 refresh_catalog.py --catalog ~/go/lib-catalog-data \
  --records-from tests/sample_records_delta.jsonl --out /tmp/refresh-demo
python3 refresh_catalog.py --self-test          # 内置 19 条断言（不联网）
```

---

## 4. 增量刷新 `refresh_catalog.py` 详解

### 4.1 为什么是「首字符桶 + sort=date + 已知 mms 早停」

读了 `scrape.py` 之后的取舍：

* `scrape.py` 的框架是**首次全量**设计——从 36 个首字符种子出发做「细分探测 → 叶子批量抓 → 缺口补抓」，
  断点 `progress.json` 记录的是**任务队列进度**；每次运行都会把整棵前缀树重走一遍，全量约**数万次**请求。
* 增量场景每周新增通常只有几十到几百本，重走全量是浪费。而 Primo 支持 `sort=date`（入藏/编目日期倒序），
  于是本脚本改成 **date-sweep 早停**：
  1. 逐桶请求 `q=holding_call_number,begins_with,<桶>&sort=date&limit=500`（36 个桶覆盖所有数字/字母开头的索书号）；
  2. 遇到**连续 `--stop-after-known`（默认 200）条已在库 mms** 即认定该桶已追平；
  3. 稳态下每桶通常 1 页，**全量刷新通常 <100 次请求**（而非数万次）。
* `sort=date` 让"新到馆"必然出现在第 1 页，新开架位（全新前缀）也落在某个首字符桶里，不会漏。

**分工**：首次全量 → `scrape.py`(+`recovery_crawl_v3.py`)+`process.py`；日常增量 → `refresh_catalog.py`。

### 4.2 流水线五个阶段

| 阶段 | 做什么 | 断点/幂等 |
|---|---|---|
| A 取数 | 逐桶 `sort=date` 翻页，抽 `pnx.display` + `delivery.holding` 字段（与 `scrape.py.extract_record` 同口径），按 `mms` 合并馆藏 | `state.json` 记每桶 `offset / consecutive_known / done`；重启后继续；已在 `records_delta.jsonl` 里的 mms 不重复写 |
| B 编译 | 记录 → `cards.jsonl` **同字段同口径**卡片（`mms/title/creator/publisher/year/language/type/hc/loc/cn/cls/cls2/src`）；`cn/cls/cls2` 用 `compile_cards.classify_cn` 的逐字副本解析索书号；`loc` 用 `process.py` 的馆名/子库/书架格式 | 跳过已在库 mms；`--records-from` 可离线重跑 |
| C 归类 | 新书 → **现有**主题节点（见 §4.3） | 确定性：同输入同输出（平局按节点 id） |
| D 出包 | `cards_delta.jsonl` + `card_topics_delta.jsonl`(+可读 TSV) + `vocab_gap_report.json` + `manifest.json`(sha256) + `MERGE.md` | 原子写 |
| E 安全 | 速率安全带 + 退避冷却 + `--max-requests` 预算 + `--dry-run` | `state.json` 每页落盘 |

### 4.3 归类口径（**硬约束：绝不新增主题节点**）

* 词表 = `<catalog>/topics/nodes.json`（当前 5,507 节点 = kw 5,158 + cls 349）。
* 切词 `tokenize()`：英文/数字 token + 中文连续串 bigram（与 `catalog_vector.tokenize` 同规则）。
* 候选 = **标题中出现的词表 CJK 词**（子串枚举，避免 bigram 链式合并从中间起链而漏掉完整词）
  ∪ 标题 token 命中的词表项（含 ASCII 词）。
* 词权 `score(term) = Σ idf(组成 token)`（ASCII 精确命中；CJK 取相邻 bigram 之和，标题内 tf × idf）。
* 取 score 前 `--topics`（默认 5）个 **kw** 节点；cls 类目节点不占名额（与主题图 P2 口径一致）。
* **未入词表的新词不会成为节点**：只写进 `vocab_gap_report.json`（含"极大的未登录子串"与原始 bigram 计数），
  由维护者人工决定是否纳入下一版 P1 词表。

### 4.4 产物与合并

见每次运行生成的 **`MERGE.md`**（含逐条命令、校验方法与回滚步骤）。要点：

```bash
cp cards.jsonl cards.jsonl.bak-$(date +%Y%m%d)
cat refresh-YYYYMMDD/cards_delta.jsonl        >> cards.jsonl
cat refresh-YYYYMMDD/card_topics_delta.jsonl  >> card_topics.jsonl   # 行序天然对齐（都追加在末尾）
wc -l cards.jsonl card_topics.jsonl                                  # 两行数必须相等
```

派生文件（`index/`、`clusters*`、`topics/edges.csr.npz`）**不会自动更新**——需要维护者重跑构建链；
只做"书 → 主题"查询的社区使用者可跳过。

---

## 5. 自动化调度指南

三种方式任选；**共同前提**：跑之前先把现有 `cards.jsonl` 放在 `--catalog` 指向的目录里（增量判定靠它）。

### 5.1 cron（Linux / macOS，最省事）

```cron
# 每周一 03:30 增量刷新；flock 防重入；日志按周轮转
30 3 * * 1  cd /opt/library-crawler && /usr/bin/flock -n /tmp/librefresh.lock \
            /usr/bin/python3 refresh_catalog.py \
              --catalog /srv/lib-catalog-data \
              --out /srv/lib-catalog-data/refresh-$(date +\%Y\%m\%d) \
              --max-requests 3000 >> /var/log/library-refresh.log 2>&1
```

* `flock -n`：上一次没跑完就不再叠加（爬虫重入会导致重复请求）。
* 若希望"跑完自动合并"：追加一行 `&& bash scripts/merge-delta.sh`（自行按 `MERGE.md` 写，注意先备份）。
* macOS 用 `launchd`（`~/Library/LaunchAgents/*.plist`）等价替换，`StartCalendarInterval` 配周任务。

### 5.2 Windows 任务计划

PowerShell 包装脚本 `refresh.ps1`：

```powershell
# refresh.ps1 —— 放到 C:\library-crawler\
$ErrorActionPreference = "Stop"
$root = "C:\library-crawler"
$out  = Join-Path $root ("refresh-" + (Get-Date -Format "yyyyMMdd"))
Set-Location $root
& python refresh_catalog.py --catalog "C:\lib-catalog-data" --out $out --max-requests 3000 `
    *>> (Join-Path $root "refresh.log")
```

注册每周任务（管理员 PowerShell）：

```powershell
schtasks /Create /TN "LibraryCatalogRefresh" /SC WEEKLY /D MON /ST 03:30 `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\library-crawler\refresh.ps1" `
  /RU SYSTEM /RL HIGHEST
schtasks /Query /TN "LibraryCatalogRefresh" /V /FO LIST   # 核对
```

* 勾选 **Run whether user is logged on or not**；机器需能访问 `sustc.primo.exlibrisgroup.com.cn`。
* 若公司/校园代理拦网，设置 `HTTPS_PROXY` 或在任务里加 `netsh winhttp set proxy ...`（并按需关闭）。

### 5.3 GitHub Actions（模板见 `.github-workflows-template/library-refresh.yml`）

使用步骤：

1. 把 `library-refresh.yml` 复制到仓库的 `.github/workflows/` 下（模板目录名带 `-template` 是为了避免未启用时就被 Actions 扫描）。
2. 仓库 Secrets/Variables 里配置（可选）：`CATALOG_URL`（现有发行包的下载地址，`.tar.gz`/`.zip`）。
   工作流会：下载现有目录 → 跑 `refresh_catalog.py` → 把增量包作为 **artifact** 上传；
   需要自动提交时勾选 `commit: true`（会把 `cards_delta.jsonl` / `card_topics_delta.jsonl` 提交到一个 `data-refresh/<日期>` 分支）。
3. **网络前提（实测）**：GitHub 托管 runner 访问 `https://sustc.primo.exlibrisgroup.com.cn` 可达
   （公网 DNS + 302 跳转正常；Primo 走标准 443，无需登录）。抓取默认只跑**几十~几百次**请求，远低于速率红线。
4. **若托管 runner 不可达**（区域出口/校园网策略/站点侧限流）：改用 **self-hosted runner**，
   在校园网内网机器上注册 runner 即可；模板文件里给了 `runs-on: [self-hosted, library-net]` 的注释块，
   并把 `--min-interval` 调大（如 `0.5`）以示礼貌。
5. 定时：模板用 `cron: '30 19 * * 0'`（UTC 周日 19:30 = 北京时间周一 03:30）；也可用 `workflow_dispatch` 手动触发。

### 5.4 长跑守护（首次全量）

`keeper.sh`（进程看护）+ `watchdog.sh`（完成收尾）是首次全量的组合；日常增量通常 1~2 分钟即可跑完，
**不需要**常驻守护。若在服务器上做无人值守全量，建议改用 `systemd` timer/service：

```ini
# /etc/systemd/system/library-refresh.service
[Service]
Type=oneshot
WorkingDirectory=/opt/library-crawler
ExecStart=/usr/bin/python3 refresh_catalog.py --catalog /srv/lib-catalog-data --out /srv/lib-catalog-data/refresh-latest
# /etc/systemd/system/library-refresh.timer
[Timer]
OnCalendar=Mon 03:30
Persistent=true
```

---

## 6. `--catalog` 目录需要什么

```
lib-catalog-data/
├── cards.jsonl 或 cards.jsonl.gz     # 必需：现有书目卡片（增量判定 + 归类 idf 回退来源）
├── index/idf.npy + index/vocab.json  # 可选：与发行索引同源的 idf（缺失则现算 df）
└── topics/nodes.json                 # 必需：主题词表（归类只允许命中其中已有节点）
```

---

## 7. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志出现 `HTTP 429/400 ... cooldown 15s` | 触发对端限流 | 脚本自动退避重试；持续出现请调大 `--min-interval`（如 0.3）并减少 `--max-requests` |
| 中途 Ctrl-C / 掉线 | — | 直接重跑：`state.json` 从上次页继续，`records_delta.jsonl` 里已有的 mms 不会重复写 |
| `[idf] 来源 cards.jsonl 现算` | 没有 numpy 或没有 `index/idf.npy` | 正常回退，功能不受影响；想用发行索引的 idf 就 `pip install numpy` |
| 合并后 `cards.jsonl` 与 `card_topics.jsonl` 行数不等 | 合并顺序出错（未追加到末尾） | 见 `MERGE.md` §2：两边都**追加到末尾**才能保持行序对齐；否则按 mms 归并后重跑构建链 |
| 新书完全没有主题（`cards_without_topics` 偏高） | 新词不在现有词表（例如新学科名） | 这是**硬约束的预期行为**：看 `vocab_gap_report.json`，由维护者决定是否在下一版 P1 扩词表 |
| GitHub Actions 里 403/超时 | runner 出口被限 | 换 self-hosted runner（见 §5.3 第 4 点）或调大 `--min-interval` |

---

## 8. 目录结构与自测

```
library-crawler/
├── scrape.py                        # 首次全量
├── recovery_crawl_v3.py             # 缺口补抓
├── process.py                       # 记录 → CSV/SQLite
├── refresh_catalog.py               # 增量刷新（新增）
├── keeper.sh / watchdog.sh / watch_recovery_v3.sh   # 长跑看护
├── requirements.txt
├── README.md
├── .github-workflows-template/
│   └── library-refresh.yml          # Actions 模板（复制到 .github/workflows/ 启用）
└── tests/
    ├── fixtures/primo_page.json     # 罐头 Primo 响应（解析器离线测试）
    └── sample_records_delta.jsonl   # 20 条合成记录（离线演示增量流水线）
```

自测（全部离线，不产生网络请求）：

```bash
python3 refresh_catalog.py --self-test                 # 19 条断言：分词/合并/分类号/卡片口径/归类约束/速率护栏
python3 refresh_catalog.py --catalog <数据目录> --fixture-docs tests/fixtures/primo_page.json --out /tmp/t1
python3 refresh_catalog.py --catalog <数据目录> --records-from tests/sample_records_delta.jsonl --out /tmp/t2
```

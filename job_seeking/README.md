# job_seeking · 搜岗 → 打分 → 短名单 → 投递 → 台账

一套只在本地跑的个人求职流水线：按关键词从猎聘搜岗，拉 JD 正文算关键词匹配度，
出短名单，**确认后**自动投递，逐行记台账。

设计上只认两条底线：

1. **判不出来就说判不出来。** 抓取失败记 `unknown`、分数留空、下次重试，绝不给默认分——
   静默算 0 分会让「抓取坏了」看起来像「岗位不匹配」，是最难查的那种错。
2. **宁可漏记，不可假记。** 投递结果判不出时**不写台账**。假记一条「已投」会让这个岗位
   被永久排除；漏记还能人工补。

## 怎么跑

本机的 `python` / `python3` 是 WindowsApps 假壳（退出码 49、无输出），`py` 也不在 PATH。
唯一可用的是 uv，所以**所有命令都走 uv**：

```bash
cd job_seeking

# 0) 自检：MCP 通道 + 令牌是否可用（只读）
uv run --no-project python scripts/liepin.py --probe

# 1) 搜岗入池（按 jobId 去重；额度敏感，先 1 页）
uv run --no-project python scripts/search.py --pages 1

# 2) 拉正文打分（正文用完即弃，不落盘）
uv run --no-project python scripts/score.py

# 3) 出短名单（按匹配度降序、排除已投、默认取前 15）
uv run --no-project python scripts/shortlist.py

# 4) 投递：先看 dry-run 清单，确认无误再加 --confirm
uv run --no-project python scripts/apply.py --list shortlists/短名单_YYYYMMDD.csv
uv run --no-project python scripts/apply.py --list shortlists/短名单_YYYYMMDD.csv --confirm
```

第 4 步是**外部且不可逆**的动作。`--confirm` 之前不会发出任何请求，dry-run 就是给你看的。
确认清单没问题、你本人点头之后，才加 `--confirm`。

## 文件

```
job_seeking/
├── criteria.md          打分标准：关键词 + 权重（唯一真源，你维护）
├── config.json          搜索词 / 城市 / 每词页数 / 每轮上限 / matcher 选择
├── pool/jobs.csv        岗位池（jobId 为键 + 搜索字段 + 分数/命中词）
├── ledger.csv           投递台账（投递去重的唯一真源）
├── shortlists/          每轮短名单（md 给人看，csv 给 apply.py 读）
└── scripts/
    ├── liepin.py        MCP 客户端（共享模块；--probe 自检）
    ├── matcher.py       Matcher 接口 + KeywordMatcher（EmbeddingMatcher 预留）
    ├── store.py         池与台账的读写（applied_ids() = 去重判断的唯一出处）
    ├── search.py        搜岗 → 入池
    ├── score.py         拉正文 → 算分 → 写回池
    ├── shortlist.py     排序 + 排除已投 + 截断
    └── apply.py         投递（默认 dry-run，--confirm 才真投）
└── tests/               三层测试：单元 / 集成（本机假服务）/ 端到端（真子进程）
```

`pool/`、`ledger.csv`、`shortlists/` 已在 `.gitignore` 里挡住——里面有真实公司名和岗位信息。

## 测试

```bash
cd job_seeking
uv run --no-project python -m unittest discover -s tests -t tests
```

89 个测试，三层，全部只在 tmp 里跑、全程不出网（行覆盖 95%）：

- **单元**：同进程直接调各脚本的 `main(argv)`，用 `store` 的路径常量重定向到 tmp 隔离。
- **集成**：网络指向 `tests/fake_liepin.py`——一个只绑 `127.0.0.1` 的假猎聘。真跑的是
  真实的 HTTP 请求、SSE 解析、正则抽正文，不是「某个函数被调用过」。
- **端到端**：把项目拷进 tmp、`USERPROFILE` 指向假家目录（于是 `~/.workbuddy/mcp.json`
  解析到夹具），用真子进程按顺序跑完 search → score → shortlist → apply。

`--confirm` 分支只在指向本机假服务时被测试，且跑之前会断言地址是 `127.0.0.1`。
真实的 `pool/`、`ledger.csv`、`shortlists/` 前后字节一致，有一条测试专门钉这件事。

## 打分怎么算

`criteria.md` 里一张权重表，算出覆盖率：

```
匹配度 = 命中关键词的权重和 ÷ 全部权重和 × 100
```

纯字符串包含（不区分大小写），不做分词、不做语义。改权重、加词删词只需要动 `criteria.md`，
脚本不用改。

**改口径会让已有分数失效，这一点脚本自己会管。** 每个岗位记着它的分数是按哪一版口径算的
（`pool/jobs.csv` 的 `criteriaFp` 列，取词表+权重的短哈希），所以：

```bash
$ vim criteria.md          # 比如加一行 | Agentic | 1 |
$ uv run --no-project python scripts/score.py
⚠️  打分口径变了（当前 keyword:...）：59 个岗位的分数是旧口径算的，本次一并重算。
```

`score.py` 会把「旧口径」和「没打分」一视同仁地重算，**不需要你加 `--rescore`**；
`shortlist.py` 则直接排除旧口径的行并报数，绝不产出一张新旧口径混排的名单
（混在一起时你没法从分数上看出哪一行是旧的）。

指纹哈希的是**解析后的词表**而不是文件字节，所以改注释、加空行、调行序都不会触发重算——
只有真正会改变分数的改动（加词/删词/改权重/换 `matcher`）才会。

**这是有意为之的粗糙版本**，代价是明显的：关键词堆得多的 JD 会虚高，非产品岗
（比如「交付总监」「销售经理」「测试工程师」）只要词命中就会排进来。要换成语义匹配，
填 `config.json` 的 `"matcher": "embedding"` 会**直接报错退出**，而不是悄悄退回关键词——
先把 `matcher.py` 里的 `EmbeddingMatcher` 实现掉再用。

## 外部依赖的契约（实测，不是推测）

| 事项 | 实测结论 |
|---|---|
| MCP 端点 | `https://open-agent.liepin.com/mcp/user`，协议 `2024-11-05` |
| 搜索工具 | `user-search-job`，**`page` 从 0 开始**，每页 20 条 |
| 投递工具 | `user-apply-job`，参数 `jobId`(数字) + `jobKind`(字符串) |
| 投递返回 | `{"data": {"result": "应聘成功"}, "errCode": 0}`（成功）｜`{"data": {"result": "应聘失败: 您已投递过该职位！"}, "errCode": 0}`（重复投递），两种均实测于 2026-09-23。**两种情形 `errCode` 都是 0**——它只表示「请求被处理了」，不是成功判据 |
| `jobKind` 从哪来 | **就是搜索返回的 `jobType`**，直接透传。实测同一批里既有 `"1"` 也有 `"2"`——不要假设它恒为 `"2"`，也不要自己推导 |
| JD 正文 | 只能从 `jobDetailUrl` 的页面里取，正文在 `<dd data-selector="job-intro-content">` 内 |
| 不存在的岗位 | 返回 **HTTP 200** + 一个 5KB 的「此页面似乎不存在」占位页。所以 200 ≠ 岗位页存在 |

## 安全闸门

1. `apply.py` 不带 `--confirm` **绝不外呼**：没有 `--confirm` 时它在循环之前就 return，
   一个请求都不会发。这条是实测过的——把 `apply_job` 换成「一被调用就抛异常」的桩，
   跑 dry-run 确认零调用、退出码 0。
2. 单轮上限默认 15，`config.json` 的 `max_per_round` 或 `--max` 可调。
3. 台账是投递去重的唯一真源；`unknown` 结果**不进台账**，且会把 jobId 单独列出来提醒人工补录。
4. 猎聘令牌只从 `~/.workbuddy/mcp.json` 读，**只读、不复制、不落盘、不打印**。本目录里没有任何令牌。
5. 抓取/接口失败一律显式报错，没有 `except: pass`，也不静默降级成 0 分或「没搜到」。

## 已知边界

- **没有简历环节。** 本流程不产出、也不保存任何一岗一版简历：池子里只有 jobId / 链接 / 分数，
  抓到的正文用完即弃。将来如果真加了简历环节，必须同批补一个投后清理步骤并把结果写进台账，
  否则文件会开始累积。
- **投递回包两种情形都已实测**（2026-09-23）：成功 `{"data": {"result": "应聘成功"}, "errCode": 0}`，
  重复投递 `{"data": {"result": "应聘失败: 您已投递过该职位！"}, "errCode": 0}`。
  注意两种情形的 `errCode` **都是 0**，所以判定逻辑**不碰 `errCode`**，
  只看 `data.result` 里的中文，并且先判失败标记再判成功标记。
  回包装不下这两种形态的第三种（既无成功也无失败字样）会记 `unknown` 且不写台账。
- **站点改版会让抽取失效。** 抽不到正文时报的是**事实**（HTTP 状态、页面字节数、标题），
  不给一个猜的原因——猜的原因（比如「改版了」）会让人往错方向查。
- 猎聘搜索和岗位页都有额度/频率限制，`--pages` 默认保守；批量打分是逐岗串行请求。

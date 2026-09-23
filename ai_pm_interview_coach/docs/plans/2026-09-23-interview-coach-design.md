# 面试出题教练 设计

日期：2026-09-23　状态：已确认，未实现

## 一句话

`ai_pm_interview_coach/` 一套本地 CLI 工具：脚本只做确定性的事，搜素材、出题、判分由
LLM（会话中的 Agent）临场做，再把结果通过脚本落库。

## 已确认的决定

| 主题 | 决定 |
|---|---|
| 形态 | 本地 CLI 脚本（方案 2），不是会话技能、不是网页应用 |
| 分工 | 脚本 = 工具（读简历、存取题库、存取记录）；智能活全由 LLM 驱动 |
| 个人事实来源 | 猎聘 MCP 在线简历（`my-resume`）。真机实测：返回 `data.result` 为 2745 字符纯文本简历。**不用** `~/.workbuddy/career-facts/` |
| 题源 | 混合：LLM 搜真实面经当素材、改写出题；搜不到就按简历生成并明说。另：用户不定期给真题资料，导入题库 |
| 出题靶子 | 简历为准 + 岗位可选（call 时可指定 target） |
| 留痕 | 记每题结果（题、回答、判定、日期、来源），**不做**间隔重复 |
| 令牌代码 | 从 job_seeking `load_endpoint()` **复制** ~25 行进 `resume.py`，两项目解耦 |

## 红线

1. **只读简历。** 真机 14 个工具里 9 个是写简历的（`add-*` / `modify-*`）。`resume.py`
   把工具名硬编码为 `my-resume`，不接受任何参数替换。
2. **真实数据不入版本库。** `bank/`、`attempts/` 进 `.gitignore`（含简历项目细节与用户回答原文）。
3. **判不出就说判不出。** `verdict=unknown` 照样入账；宁可漏记，不可假记。

## 组件

| 脚本 | 职责 | 联网 |
|---|---|---|
| `scripts/resume.py` | 读在线简历并打印。唯一联网入口 | ✅ |
| `scripts/bank.py` | 题库：`add` / `list` / `sample` / `show` / `remove` | ❌ |
| `scripts/attempts.py` | 记录：`record` / `history` / `weak` | ❌ |
| `scripts/store.py` | 共享 JSONL 读写 + 字段校验 | ❌ |

存储用 **JSONL 不用 CSV**：题面、参考答案、回答原文都是多行长文本。

布局：

```
ai_pm_interview_coach/
├── scripts/
├── config.json             # 每轮默认题数等；用户维护
├── bank/questions.jsonl    ← .gitignore
└── attempts/attempts.jsonl ← .gitignore
```

### 数据模型

题库一行：`id`（题面指纹）、`question`、`refAnswer`（落库时写好）、`target`（可空）、
`kind`（简历深挖/岗位场景/通用）、`source`（`搜:<url>` / `生成` / `用户导入`）、`addedAt`。

**去重靠 `id`：同指纹拒绝写入并报「已存在」，不静默覆盖**——用户导入的真题与搜到的素材
撞车时要人来决定合并。

记录一行：`at`、`qid`、`answer`（用户原文）、`verdict`（对/部分对/错/unknown）、`feedback`。

## 一次 call 的流程

1. 用户 call，可带岗位（「面 XX 岗」）
2. `python scripts/resume.py` 读简历（同一会话读一次）
3. `python scripts/bank.py sample --n <每轮题数> [--target T]`；不够或要新鲜 →
   LLM 联网搜面经、改写、`bank.py add --source 搜:<url>` 落库再 sample
4. 出题 → 用户答
5. `bank.py show <id>` 取参考答案 → 判 → 给 **verdict + 点评 + 参考答案（答对也给）**
6. `attempts.py record` 落账
7. 随时 `attempts.py weak` 看哪里反复错

## 错误处理（全部响亮）

- 简历读不到（配置缺失 / `errCode≠0` / `result` 空）→ 非零退出，不用旧缓存
- 搜不到好素材 → 明说「没搜到，改用生成」，`source=生成`，不假装搜过
- `add` 指纹撞车 → 报错退出，不覆盖
- 判不出 → `unknown` 入账

## 测试（三层，pytest）

- **单元**：store/bank/attempts 读写、去重、字段校验；数据重定向 tmp
- **集成**：假 MCP 只注册 `my-resume` 但故意声明 9 个写工具存在；断言 `resume.py` 发出的
  `params.name` 永远是 `my-resume`，且假令牌不出现在任何输出里
- **端到端**：真子进程跑 `sample → add → record → weak`，断言真实 `bank/`、`attempts/` 前后字节一致

---
name: evidence-driven-claim-writer
description: Split a draft into checkable claims, bind each claim to its cited sources, grade evidence strength from study design and sample size, and flag overclaims, causal language and topical mismatches. Use when a writing task must show claim-evidence mapping, evidence levels and honest uncertainty.
---

# 文献证据驱动写作与论断审计

## 用途与适用条件

把需要文献支撑的稿件拆成**可判定论断单元**，为每条论断绑定所引文献，按研究设计与样本量给出证据等级，识别过度断言、因果误用、悬空引用与主题错配，并给出逐条修订建议。

适用：

- 任务要求"论断清单—证据表—成稿"三段交付。
- 需要判断"这句话的证据够不够、说得准不准"。
- 有文献库（题名/摘要/片段）与带引用标记的稿件。

不适用：需要真实检索与全文获取、需要正式 GRADE 评级、需要生成完整成稿（本 Skill 只审与建议，不改写全文）。

## 输入

| 输入 | 位置 | 说明 |
|-|-|-|
| `case.json` | `/input/case.json`（`--case` 可覆盖） | 稿件取自 `manuscript` / `draft` / `text` / `content` / `claims`；文献库取自 `references` / `evidence` / `sources` / `library` |
| `task.md` | `/input/task.md`（自动探测） | 任务约束 |
| 输出 | `/app/output/result.json`（`--out` 可覆盖） | 结构化结果 |

文献条目字段：`key/id`、`title`、`year`、`type`、`authors`、`abstract` / `findings` / `excerpt`。

## 处理流程（对应评分维度）

1. **论断切分**（找得到）：按标题与句末标点切分，只保留含 `[n]` / `[n,m]` / `\cite{key}` 的实质句；记录所属章节。
2. **引用绑定**：数字编号与引用键分别映射到文献库；找不到的进入 `dangling_citations`，不静默丢弃。
3. **证据分级**（说得准）：按设计与文本线索分级——5 荟萃/系统综述，4 随机对照，3 队列/病例对照，2 横断面/叙述性综述，1 病例报告/预印本/体外或动物；样本量用 `n =` 或"120 participants"抽取，仅作参考。
4. **主题一致性**：论断与文献题名/摘要做词项重叠，`aligned` / `weak_overlap` / `no_lexical_overlap` 三态，提示人工确认是否真的支持。
5. **过度断言检查**：强断言词（proves/demonstrates/confirms/clearly/always/never/cause/导致…）与证据等级不匹配即 `overclaim`；弱证据上使用因果动词即 `causal_language_on_weak_evidence`。
6. **修订建议**：弱证据时把因果动词改为相关性表述、强断言降级并删除强化副词；建议句写入 `suggested_revision`，不改动原稿。
7. **不确定性与缺口**：无证据论断、仅有题名无摘要、弱证据论断、悬空引用分别写入 `uncertainty` 与 `evidence_gaps`。

## 输出契约

- `case_id`：原样保留。
- `status`：`success`（有稿件）/ `partial`（仅有文献库）/ `insufficient_input`（都缺）/ `failed`。
- `result`：`claims`（逐条论断 + 绑定证据 + 等级 + 修订建议）、`evidence_table`（扁平证据行）、`evidence_gaps`、`unsupported_claims`、`draft`、`strength_scale`、`limitations`。
- 顶层另置 `claims`、`evidence_table`、`draft` 便于契约映射。
- `evidence`（论断→定位）、`uncertainty`、`errors`、`stats`（论断/文献/证据行/缺口/过度断言/悬空引用计数）、`contract_notes`。

**output_contract 处理**：声明字段逐一置于顶层；`claims`、`evidence_table`、`draft` 及别名会映射；无法产出字段置 `null` 并在 `contract_notes` 说明，不编造文献或等级。

## 异常处理

| 情况 | 处置 | status |
|-|-|-|
| `case.json` 缺失/非法 | 结构化失败，标注阶段，退出码 2 | `failed` |
| 无稿件也无文献库 | 不产出论断表，说明缺什么 | `insufficient_input` |
| 只有文献库 | 列出分级，说明无稿可审 | `partial` |
| 引用编号/键不在库中 | 记入 `dangling_citations`，不删标记 | `success` |
| 论断无引用 | 不计入 claims，写入 `uncertainty` 提示 | `success` |
| 文献只有题名、无摘要 | 仍绑定，但标记无法核验支持关系 | `success` |
| 研究设计无法识别 | 记为 `unclassified`（等级 2），提示人工复核 | `success` |

## 限制

- 证据等级是启发式，不是正式 GRADE；样本量与设计仅取自文本线索。
- 不联网核验文献真伪、撤稿或版本；不做全文检索。
- 主题一致性用词项重叠近似，同义改写可能被误判为 `no_lexical_overlap`。
- 只给逐条建议，不自动重写全文，因此交付物是审计结果 + 建议句，不是终稿。

## 最小调用示例（示例，非官方案例结果）

```json
{
  "case_id": "demo-001",
  "output_contract": {"claims": "array", "evidence_table": "array", "status": "string"},
  "manuscript": "## Results\n\nInhaled corticosteroids clearly cause a 40% reduction in exacerbations [1].",
  "evidence": [
    {"key": "R1", "title": "Case series of inhaled corticosteroids", "year": "2019", "type": "case series", "abstract": "Ten patients, no control group. n = 10."}
  ]
}
```

```bash
python scripts/run_skill.py --case /input/case.json --out /app/output/result.json --work /app/work
```

示意输出（**示例**）：`status=success`，`claims[0].support_level=weak`、`overclaim=true`，`suggested_revision` 为 "Inhaled corticosteroids are associated with a 40% reduction ...（证据等级不足：因果表述改为相关性表述，强断言降级）"。


## 自查清单

- [ ] `case_id` 与合同字段保留；未映射项已登记。
- [ ] 每条论断都绑定证据或进入 `evidence_gaps`。
- [ ] 强断言与证据等级不匹配处均已标 `overclaim`。
- [ ] `draft` 使用降级表述并保留原引用标记。
- [ ] 未编造文献、等级或结论。

## 交付保证与评分对齐

调用顺序（固定）：

1. 先运行包内脚本（若存在）：`python scripts/run_skill.py`（默认读 `/input/case.json`，写 `/app/output/result.json`）；路径不同时用 `--case` / `--output` 指定。
2. **必须交付完整成品**：脚本只做论断切分与分级；调用 Agent 必须补全 `claims`、`evidence_table`、`evidence_gaps`，并按证据强度写出**带降级表述的可用正文** `result.draft`（弱证据改相关性表述、保留引用标记）；不得只交审计表、`pending` 或“不改写全文”。
3. 最后自检：`case_id` 与输入一致；`output_contract` 每个字段都存在；`status` 取本合同允许值 `success | partial | insufficient_input | failed`；正文无 `pending`/`TODO`/空占位；数字、引用、来源可逐条回溯。

运行保证：

- 输入缺失、JSON 损坏、字段异常、输出目录不存在时，仍须写出结构化 `result.json` 并正常结束，不得崩溃或非零退出。
- 不联网、不伪造数据、不声称平台评分或官方案例结果。
- 交付物必须是可直接编辑与复核的成品，而不是流程说明。

评分对齐（本题五个维度）：

- 实际效果（40）：完整产出任务要求的最终成品，覆盖全部输入条目，可直接进入修改流程。
- 使用增益（25）：体现相对基础 Agent 的可验证改进（结构化、术语/数字/引用核对、可编辑性）。
- 创新增益（15）：保留方法学增量（分块、对齐、二次校验、版本比对等），并用结果证明其价值。
- 可靠体验（10）：异常输入有明确降级与说明，不同长度/文体/重复运行下稳定产出。
- 生态贡献（10）：用途、调用、输入输出、限制、示例、维护信息齐全，资源可被他人复用。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。

# 成长闭环：v0.3.0

本版不只分发协议文字：收工、任务身份、显式反馈、复盘状态、持久评估、月报和接续包已接入同源 `memory_growth` Module。它帮助保留可核对的成长证据，不替模型保证洞见质量。

## 能力与边界

| 层级 | 本版状态 | 不能据此声称 |
| --- | --- | --- |
| 行为协议 3.3.0 | 通用条款与可选规则安装；增加最小补证、异常补救与恢复条件 | 写入规则即代表所有 Agent 已正确执行 |
| 成长执行、记录与投影 | 本地 Python，零新增运行依赖；显式启用 | 默认调用云模型或自动给任务打高分 |
| 复盘 | 用已有 Agent 生成受证据约束的 JSON，经 Interface 校验后作为同任务新修订保存 | 契约完成等于洞见有效；模型自报 verified 等于独立验证 |
| 工作台反馈 | 服务器解析回执与文件版本；可选登记结果、命中、漏判、无效打扰；未填保持未知 | 采用等于业务效果；重复点击等于独立案例 |
| 方法候选 | 追溯独立任务证据，生成待复验方法卡；不改全局规则 | 候选已成为正式 Policy |
| 下一任务 | 原有接续包增加成长状态、反馈与待核对停止规则 | 已公开完整 TaskMemoryPacket 编译器 |
| 高级记忆运行时 | **World Fact、L2/L3 Policy 派生与完整 TaskMemoryPacket 仍未公开** | 本版已激活作者本地的高级试点或多项目生产运行时 |

普通网页模式继续可用。新建普通配置默认 `disabled`；旧配置缺字段为 `legacy_unconfigured`，有效行为仍为关闭。安装协议、启用记录、提交复盘、验收效果是不同的动作。

## 启用，不修改全局规则

从代码目录执行，路径换成自己选定的目录：

```powershell
python -B -m memory_hub setup --vault "C:/my-memory" --growth-mode enabled
python -B -m memory_hub growth status --vault "C:/my-memory"
```

正式回执与反馈仍在 Vault。新成长运行时在 Vault 同级的 `my-memory.growth-runtime`，不能位于正式 Vault 或源码内。可用 `setup --growth-runtime-root "另一个专用目录"` 指定。原有普通工作台快照仍保留旧位置。迁移已建立水印的来源不能直接改路径/删状态消警，需保留原件并另行核对迁移。

关闭记录：`setup --vault "C:/my-memory" --growth-mode disabled`。这不删除历史、不撤销用户决定、不卸载以前明确批准的 Agent 规则。记录开关不是 Agent 行为规则开关。

## 新任务与修订

```powershell
python -B -m memory_hub close --vault "C:/my-memory" --project "我的项目" --task "比较期分析" --new-task --request-id "comparison-first-v1" --status stage-complete --completed "已形成有证据的分析" --next-action "本人核对" --evidence "C:/my-project/result.md" --verification "写实际运行的检查和结果"
```

仅当确为新的独立任务使用 `--new-task`。保存返回的 `task_id` 和 `receipt_id`；接续同一任务用 `--task-id`，明确修订还可传 `--revises-receipt-id`。旧基线已有新修订时会拒绝覆盖，先读取最新结果。无明确身份的旧调用仍可收工，但标为 `identity_unresolved`，不能用来凑独立方法证据。

一次请求重试保留同一 `--request-id`，内容改变用新请求键；同键不同内容会拒绝。发生写入异常会恢复已知由本事务写入的版本，遇到未知并发版本则停止并保留快照，不猜测覆盖。断电/进程崩溃后的遗留锁不自动抢占；须先确认无写入者、核对写前快照与缺失项，不能把重试回显当成完整提交。

## 触发与复盘

触发依赖确定性事件，不靠“任务听起来重要”。例如 `repair_failed` 达两次、`user_confirmed_omission`、`key_assumption_overturned`、`major_rework`、`production_incident`、`user_requested_retrospective`；影响事件包括生产、隐私、关键口径、架构、对外结果、资金合同和安全边界。未知新事件会在写入前拒绝。影响可选 `unknown/ordinary/high/safety`，非 unknown 必须给理由；单独标高影响不等于每次强制调用模型。

Agent应只登记实际发生且有依据的事件：可在收工时追加 `--growth-event 事件码`。工作台普通“需要修改”不会擅自变成用户确认遗漏；明确选择“遗漏影响判断”并写具体说明，才形成待复盘证据。反馈账本是主来源，界面不并发改写正式成长日志。

无评审响应时保留 `pending_llm`；结构/字段/引用错误最多一次纠错，仍失败则保留待处理；证据不足为 `insufficient_evidence`。外部评审错误只保存错误类别，不把可能含凭证的 stderr 写入记忆或纠错提示。

让自己已有的 Agent 读取证据范围和 JSON 要求：

```powershell
python -B -m memory_hub growth prompt --vault "C:/my-memory" --receipt-id "实际回执ID"
python -B -m memory_hub growth review --vault "C:/my-memory" --receipt-id "实际回执ID" --response-file "review.json"
```

`review.json` 来自真实评审，不能为消除 pending 伪造完成。该命令追加同一任务的新收工修订，不修改旧回执。它不自动启动厂商 CLI 或调用付费 API；使用已有 Agent 的成本、权限和隐私限制仍由其平台决定。Python 调用者也可给 `close_task(..., growth_reviewer=callable)` 注入适配器。

## 结果、评估和月报

- 成果采用、本人报告的结果、协议表现、复盘契约和方法复验分开存。旧反馈或未作判断不自动补分；再次普通保存保留已明确观察，显式改选未知才清除当前观察，旧事件保留。
- 命中/漏判/无效打扰只统计显式登记的判断，未判定不进分母；这是报告性记录，不是客观自动成功率。专项合成验收和自然工作样本必须分开。
- 月报按任务去重，但保留回执版本数量；覆盖当月、前月与修订链相关月份。人工复核、独立审查和结果回看区经持久账本保留，不被重新生成覆盖。

```powershell
python -B -m memory_hub growth report --vault "C:/my-memory" --month "2026-11" --dry-run
python -B -m memory_hub growth report --vault "C:/my-memory" --month "2026-11"
```

## 异常恢复

正式收工成功后，成长投影失败只产生 pending，不回滚已提交事实。反馈决定也先保存；同步失败保留原事件作为 outbox，界面明确待处理。源前缀编辑、删除、重排、截断、同 ID 冲突、路径逃逸或坏回执哈希不得静默修复。

先保留原历史、当前文件、写前快照和错误；核对影响范围与责任方，修复权限或恢复可验证的原始版本后，按原回执重放：

```powershell
python -B -m memory_hub growth replay --vault "C:/my-memory" --receipt-id "原回执ID"
```

这是成长记录/评估的重放，不是尚未公开的 L2/L3 运行时命令；也不是重新发送用户反馈或重新跑模型。恢复条件未满足时继续 pending，不改哈希、不排序历史、不删除状态绕过保护。

## 维护和验收

`memory_growth/source-manifest.json` 给出同源文件 SHA256。维护者可用 `scripts/sync_growth_module.py` 检查/机械同步授权源；不是分别手改两套算法。哈希证明字节一致性，不证明作者身份、证据真实性或模型质量。

当前精确验收覆盖见 [本版升级清单](growth-upgrade.md)。Windows 网页是本轮实机对象；其他系统/Agent、自然任务长期效果和高级派生层仍须分别复验，不能由单元测试或合成页面推断通过。

# AI Agent Memory Hub

一个可由 Claude Code、Codex、WorkBuddy、Gemini、Qoder 等本地 Agent 协助部署的本地优先 AI 记忆中枢。仓库只包含通用代码、规则模板和工作台，不包含作者的记忆、项目数据、账号、密钥或个人配置。

## 它解决什么问题

- 多个 Agent 读取同一个 Obsidian Vault，复用项目事实、决策、证据和下一步。
- Agent 在任务结束时生成可追溯的 worklog、事件回执和工作台快照。
- 在保留用户原有规则的前提下，把记忆中枢规则写入指定 Agent 的全局或项目规则文件。
- 可选启用《成长型 AI 协作协议 V3.2.1》，让 Agent 主动区分事实、推断、盲区和待验证假设。
- 提供跨平台网页工作台，以及仅支持 Windows 10/11 的桌面工作台。

## 支持范围

| 能力 | Windows 10/11 | macOS |
|---|---:|---:|
| Obsidian 记忆库与 Python CLI | 支持 | 支持 |
| 网页工作台 | 支持 | 支持 |
| Windows 桌面工作台 | 支持 | 不支持 |

这不是自动扫描并修改电脑的一键安装器。推荐把仓库网址或 ZIP 交给本地 Agent，让它遵循 [Agent 部署说明](docs/agent-deployment.md)：先体检、再输出计划、经用户确认后才修改规则和安装组件。

## 给 Agent 的最短入口

```text
请阅读仓库根目录 AGENTS.md 和 docs/agent-deployment.md。先执行只读体检，逐项向我确认 Vault、规则作用域、成长协议和工作台选择；输出计划供我审阅，在我明确同意前不要修改任何全局规则或安装软件。
```

## 命令概览

```bash
python -m memory_hub doctor --json
python -m memory_hub plan --vault "/path/to/vault" --agent codex --rule-scope global --growth-mode enabled --workbench web --output install-plan.json
python -m memory_hub install --plan install-plan.json --yes
python -m memory_hub close --vault "/path/to/vault" --task "任务名" --status completed --completed "完成内容" --next-action "下一步" --evidence "证据路径"
python -m memory_hub verify --vault "/path/to/vault"
```

`install --yes` 只能在用户审阅计划并明确同意后执行。已有规则文件会被保留，受管区块外的内容不会被覆盖，修改前的版本会备份到 Vault 的 `.memory-hub/backups/`。

## 仓库结构

- `memory_hub/`：环境体检、安装计划、规则写入、任务收工和快照生成。
- `protocols/`：通用成长型 AI 协作协议，不含个人资料。
- `workbench/web/`：Windows/macOS 均可使用的网页工作台。
- `workbench/desktop-windows/`：Windows 10/11 桌面工作台源码与脚本。
- `docs/`：Agent 部署协议、平台边界和验证说明。
- `tests/`：纯临时目录测试，不读取作者的真实 Vault。

## 隐私边界

不要把真实 Vault、日报、项目页、数据库连接串、token、cookie、`.env`、Agent 私人全局规则或安装回执提交到公共仓库。发布前运行测试与敏感信息扫描；详见 [安全说明](SECURITY.md)。

## License

[MIT License](LICENSE)：允许他人使用、复制、修改和再发布，须保留版权与许可证声明；软件按现状提供，不承诺担保。

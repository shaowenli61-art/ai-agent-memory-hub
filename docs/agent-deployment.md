# Agent 驱动部署说明

普通用户先从 [本地部署入口](../INSTALL.md) 开始：Agent只读体检后，按本人选择启动体验或真实网页工作台，无须先改全局规则、选成长协议或装桌面程序。

以下是可选的Agent共享规则安装流程，只有用户要求该能力才使用。执行者为用户本地已有的Agent，应核实环境、展示具体修改计划后完成可验证部署。

## 0. 不可越过的边界

- 体检阶段只读。不得安装软件、创建 Vault、写规则或移动用户文件。
- 修改任何全局 Agent 规则前必须获得用户明确许可。
- 不能把用户已有的记忆、日报、个人资料、凭证或绝对私人路径复制进本仓库。
- 不覆盖规则文件全文；只维护 `AI_MEMORY_HUB_RULES_V1` 区块，并保留备份。
- macOS 不安装 Windows 桌面工作台。

## 1. 只读体检

在仓库根目录执行：

```bash
python -B -m memory_hub doctor --json
python -B launch.py --check
```

随后补查当前版本尚不能自动确认的项目：

- Python 是否为 3.11 或更高版本。
- 用户是否已安装 Obsidian；若未安装，说明它不是生成 Markdown 的硬依赖，但会影响可视化知识管理和 `obsidian://` 证据跳转。
- 用户本机有哪些目标 Agent，以及它们真实采用的全局/项目规则文件。
- Windows 桌面方案是否具备 .NET 9 SDK 和 WebView2 Runtime。
- 网页方案是否有可用浏览器。

不要仅依据“某个目录存在”就断言对应 Agent 已正确安装；目录和命令只是线索，必要时运行该 Agent 的版本命令验证。

## 2. 只问会改变部署路线的问题

仅在本节高级部署中确认以下四项；已有明确选择直接沿用，不重复询问：

1. **Vault**：使用哪个已有 Obsidian Vault，还是创建一个新的空 Vault；记录绝对路径。
2. **规则作用域**：写入全局规则，还是只写某个项目；全局规则影响面更大。
3. **成长协议**：`enabled` 或 `disabled`。启用后会把 V3.2.1 通用协议放入受管区块。
4. **工作台**：`none`、`web` 或 `desktop`；`desktop` 仅限 Windows 10/11。

如果用户选择多个 Agent，逐个列出将要修改的规则路径。发现多个候选规则文件时，不猜测，先用该工具的实际文档或运行行为确定有效入口。

## 3. 生成可审阅计划

示例：

```bash
python -m memory_hub plan \
  --vault "/absolute/path/to/vault" \
  --agent claude \
  --agent codex \
  --rule-scope global \
  --growth-mode enabled \
  --workbench web \
  --output install-plan.json
```

Windows PowerShell 可把续行符改为反引号，或写成一行。向用户展示整个 `install-plan.json`，重点标出 Vault、平台、每个规则目标、规则作用域、成长协议和工作台。

## 4. 获得明确同意后安装

```bash
python -m memory_hub install --plan install-plan.json --yes
python -m memory_hub verify --vault "/absolute/path/to/vault"
```

若前置软件缺失，先说明用途、官方来源、影响范围和是否需要管理员权限，得到同意后再安装。安装依赖后重新运行体检和计划，不沿用过期判断。

## 5. 工作台

网页工作台安装在：

```text
<Vault>/.memory-hub/workbench/web
```

不能直接双击依赖 `fetch()` 的页面；从该目录启动本地 HTTP 服务，例如：

```bash
python -m memory_hub serve --vault "/absolute/path/to/vault"
```

然后打开 `http://127.0.0.1:8896/full/index.html`。服务只绑定本机；静态 HTTP 服务不能执行反馈和归档。上述 serve 命令从代码仓库根目录运行。普通启动不修改全局规则。首次配置与升级见 [正式本地部署](local-workbench.md)。

Windows 桌面端在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\workbench\desktop-windows\install-memory-hub-desktop.ps1 -Vault "C:\absolute\path\to\vault"
```

如果用户未选择桌面端，不安装 .NET SDK 或 WebView2。macOS 用户只使用网页工作台。

## 6. 日常使用与收工

Agent 完成一项任务后，根据真实状态执行：

```bash
python -m memory_hub close \
  --vault "/absolute/path/to/vault" \
  --task "任务名" \
  --status completed \
  --completed "已经完成并验证的内容" \
  --next-action "下一动作与负责人" \
  --evidence "相对 Vault 的证据路径"
```

状态可选：`active`、`completed`、`stage-complete`、`waiting`、`blocked`、`handoff`、`terminated`。不要把“等待确认”写成“已完成”。该命令会追加事件、更新当天 worklog、生成回执，并刷新网页/桌面工作台读取的快照。

## 7. 验收回执

新版可信摘要需要先登记真实项目，再在 close 命令增加 `--project "项目名称"` 与真实 `--remaining`。缺少项目归属的旧任务不会被猜测合并，任务完成不会结束项目。

交付时必须报告：

- 实际平台、Python/Obsidian/Agent/工作台前置条件。
- 用户确认过的四个选择。
- 创建或修改的绝对路径。
- 规则备份位置和安装回执位置。
- `verify` 结果、工作台实际打开结果。
- 尚未完成、被跳过或需要用户处理的项目。

“命令成功退出”不等于部署成功；至少验证一个 Agent 能读取受管规则、一次 `close` 能生成日报与回执、所选工作台能显示该任务。

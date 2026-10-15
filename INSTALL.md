# 本地部署入口

把本目录交给你已有的 Codex、Claude Code、WorkBuddy 等本地Agent，让它完整读取本文件并协助部署。普通网页工作台只需要Python 3.11+（SQLite支持FTS5）和浏览器，无须先安装Agent规则、Obsidian、桌面程序或模型。

## 直接交给Agent的话

```text
请完整读取本项目 INSTALL.md，帮我部署个人工作台。
先只读体检，不创建记忆库、不改规则、不安装依赖。报告结果后，按我已明确选择的模式继续；缺少选择时只问我是先体验还是接入真实工作，以及真实模式必要的资料目录。
优先网页模式，不自动安装全局规则、桌面程序或模型，不把虚构样例并入正式资料。沿用我已经明确授权的可逆配置与启动操作，不对普通命令重复询问。
实际验证启动入口、检索、接续、成果反馈和项目归档恢复；没有成果回执时先完成一次实际交付。报告真实验证结果和未完成项，不能只说测试通过。启动失败时保留原资料并排查。
```

## 先做只读体检

Agent从代码根目录执行；macOS/Linux可将 `python` 换为实际可用的 `python3`：

```powershell
python -B launch.py --check
python -B -m memory_hub doctor --json
```

前者检查Python、SQLite FTS5、网页资源、体验与真实服务的实际模块导入，以及发行清单（若存在）。后者补充本机工具线索。`-B`避免生成字节码缓存；两条命令都不初始化数据、不创建记忆库、不改规则、不下载模型。

只有结果 `ok: true` 才继续。浏览器和Agent目录存在只是线索，最后仍要实际打开网页。缺少Python时先说明官方安装途径；普通网页模式不安装.NET或WebView2。体检阶段不运行 `setup`、`install` 或不带 `--check` 的启动命令。

已配置的真实记忆库可进一步检查：

```powershell
python -B launch.py --check --vault "C:/my-memory"
```

尚未配置的目录会给出错误，不会自动创建。取得用户的模式和目录选择后，再按下一节进行实际配置；已有明确选择直接沿用。

## 体验模式

用户选择体验后执行：

```powershell
python -B launch.py --mode demo --no-browser
```

打开 `http://127.0.0.1:8897/full/index.html`。虚构项目与记录留在包内 `demo-data`，不会接入正式库。也可双击 `Start Workbench.cmd` 后首次选择 `2`；macOS使用 `Start Workbench.command`。省略 `--no-browser` 时会尝试打开系统默认浏览器。

控制台或Agent管理的后台进程需要保持运行；体验服务用该控制台的Ctrl+C停止。后续不带模式参数启动会读取 `local-settings.json` 中保存的选择。停止服务不会结束项目。

## 接入真实工作

用户选择代码目录之外的记忆库和可选的岗位、个人知识目录。已有外部资料只读接入；只初始化缺少的中枢文件，不导入虚构数据。

```powershell
python -B launch.py --mode real --vault "C:/my-memory" --no-browser
```

已有知识库时可追加 `--job "C:/my-job-notes" --personal "C:/my-personal-notes"`。所有示例路径都要换成用户实际选择的目录。打开 `http://127.0.0.1:8896/full/index.html`。

登记一个实际存在的项目目录，不移动成果文件：

```powershell
python -B -m memory_hub project --vault "C:/my-memory" --name "我的项目" --path "C:/my-project" --goal "项目的真实目标"
```

让Agent读取 `skills/continuous-workbench/SKILL.md`，使用接续包并在交付后真实收工。无正式回执的工作不冒充已经完成。普通网页启动、项目登记和收工都不修改全局规则，自动接入共享规则是单独可选能力。

真实模式停止：双击 `Stop Workbench.cmd`，或运行 `python -B -m memory_hub stop --vault "C:/my-memory"`。重启执行 `python -B launch.py --no-browser`，复用保存的模式、目录与端口。

## 验证与排错

从最终解压目录运行，核对页面加载、项目详情、下一步建议、资料检索、接续包、正式成果反馈/采用、项目暂停/结束/恢复；重启后确认状态仍在。基础检索覆盖已接入Markdown，模型和附件处理不是开箱即具备的能力。

- 端口占用：追加 `--port 8898` 或其他可用本机端口，按打印地址打开。服务成功绑定后才保存选择；失败不保存新的首次启动选择。
- 切换模式：明确使用 `--mode demo` 或 `--mode real --vault "实际目录"`，无须删除数据。启动设置损坏时先备份并检查 `local-settings.json`，不要删除知识库。
- `Release hash mismatch`：发行文件相对清单已改变，重新下载或核对自己做过的修改，不关闭校验或改哈希掩盖未知变化。
- 有意定制源码：可以修改GitHub源码，完整测试后运行 `python -B scripts/build_local_release.py --output "一个新的代码发行目录"` 生成自己的清单和运行包。输出目录放在源码目录外；个人配置不写进源码。
- SHA256只证明相对清单一致，不是作者签名；清单和源码同时被替换不能证明可信来源。GitHub Code ZIP通常没有发行清单，体检明确报告源码目录并允许本地运行。

## 可选高级部署

只有用户要求让Agent长期自动遵循共享记忆规则时，才使用 `docs/agent-deployment.md` 的计划与安装流程。展示规则路径、作用域和备份，取得该范围明确授权后再安装；已有授权不重复询问。

更新与回退见 `docs/local-workbench.md`。更新保留个人资料、配置与启动设置，有意定制过的源码需自行合并。默认不要求API Key、不调用云模型、不开放公网端口。Windows网页路线是当前实机验收对象，macOS/Linux需在对应机器另行验收。

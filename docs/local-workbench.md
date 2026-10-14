# 正式本地工作台部署 / Local Workbench

这是连接使用者自己的项目与知识库的源码部署包。需要 Python 3.11+（SQLite 含 FTS5）和浏览器；不附带 Python 解释器或模型权重，无需 API Key。Obsidian 推荐但不是网页运行的硬依赖。

## 首次使用与日常启动

解压到长期保留的目录，Windows 双击 Start Workbench.cmd；macOS 在终端执行 `python3 launch.py`。首次选择真实工作或虚构体验，真实模式确认记忆库及可选岗位库、个人库目录。以后自动沿用，不重复填计划、不改全局规则。

虚构模式使用包内 demo-data；真实模式不导入虚构项目。记忆库应放在代码目录外。启动选择保存在 local-settings.json，其余配置在 Vault/.memory-hub/workbench-config.json，成果决定与项目生命周期台账在 Vault/50-Agent-Workflows/90-Logs。已有项目页、任务页与规则保留，只创建缺少的初始化文件；外部知识库只读。

## Agent 接入自己的项目

在代码包根目录运行，示例路径换成自己的目录，job/personal 参数可省略：

```powershell
python -m memory_hub setup --vault "C:/my-memory" --job "C:/my-job-notes" --personal "C:/my-personal-notes"
python -m memory_hub project --vault "C:/my-memory" --name "月度经营分析" --path "C:/my-projects/monthly-report" --goal "核实变化并形成行动建议"
python -m memory_hub serve --vault "C:/my-memory"
```

项目目录必须已经存在；登记不会移动成果，同名不同目录会拒绝。打开 http://127.0.0.1:8896/full/index.html 。端口占用时加 `--port 8898`。控制台保持运行，关闭或 Ctrl+C 停止；Windows 真实模式也可双击 Stop Workbench.cmd，或 `python -m memory_hub stop --vault "C:/my-memory"`。停止服务不结束项目或外部 AI。

AI 读取 skills/continuous-workbench/SKILL.md，以当前配置读取接续包：

```powershell
python scripts/work_cycle.py --config "C:/my-memory/.memory-hub/workbench-config.json" --packet --project-path "C:/my-projects/monthly-report"
python -m memory_hub close --vault "C:/my-memory" --project "月度经营分析" --task "核实口径" --status stage-complete --completed "已核对计量口径" --remaining "等待本人采用" --next-action "本人检查结果" --evidence "C:/my-projects/monthly-report/result.md"
```

指定已登记项目后，收工生成带项目身份、时区和哈希的回执，进入摘要与候选成果；任务完成不结束项目，采用由本人决定。未指定项目的任务不会自动归属。旧回执只追加，不改写。网页每 15 秒读取快照；项目详情保留打开时上下文，关闭重开获取最新资料。

已有脱敏 ai-activity.json 可被自动发现读取；本安装器不自动监听各 Agent 原始私有日志。长期状态依赖 Agent 真实登记/收工。若要让 Agent 自动遵循共享规则，继续用 doctor → plan → 明确批准 install 的既有流程；普通启动不修改 Agent 规则。

## 定制与可选语义检索

修改正式配置，或重复 setup 明确提供变更参数。未提供的设置与自定义字段保留。可配置重点项目、发现根目录、能力地图路径和日期阈值，不修改生成快照。缺少可选能力地图/决策台账不会使页面启动失败。

基础文字召回无需第三方依赖。若使用已有本地 ONNX 中文语义模型，按需执行 `python -m pip install -r requirements-semantic.txt`，然后：

```powershell
python -m memory_hub setup --vault "C:/my-memory" --semantic-model "C:/my-models/embedding" --semantic-onnx "C:/my-models/embedding/model.onnx" --reranker "C:/my-models/reranker"
python -m memory_hub workbench-doctor --vault "C:/my-memory"
```

模型目录须含兼容 tokenizer、config 和权重；重排可选，模型许可证和资源由使用者核对。安装器不下载模型、不调用外部 API；模型未就绪明确降级为文字召回。仅 Markdown 进入当前知识检索，附件和未接入的原始聊天不在覆盖范围。

## 更新与回退

先停止服务，备份 Vault 与 local-settings.json。新包解压后运行：

```powershell
python scripts/update_local_release.py --package "新包解压目录" --target "旧代码目录"
```

更新器验证文件清单与哈希，先备份旧源码再替换白名单文件。保留启动设置、个人配置、知识库、项目页和台账；拒绝代码与 Vault 混在一个目录。源码定制会被新代码替换，旧代码有备份，需自行对照迁移。回退以更新回执的 backup 作为 package 再执行同一命令；回退只覆盖备份文件，不自动删除新版本新增的文件。

如果新版本来自 GitHub 的 Code ZIP，先在新源码目录运行 `python scripts/build_local_release.py --output "一个新的发布目录"` 生成带校验清单的部署包，再用它更新。直接下载源码也可以首次运行 launch.py。定制配置修改后重启服务生效。

不要整目录删除/覆盖个人安装，不把体验数据并入正式库。Windows 原贴边观察器沿用旧安装方式；本轮新增连续工作操作的完整验收对象是浏览器网页。

## 验收与平台边界

`python -m unittest discover -s tests -v`。实际验收：接入目录 → 摘要与建议 → 查历史 → 接续 → 登记、反馈与采用 → 归档恢复 → 重启检查设置。已验证独立 Windows 中文路径部署；macOS/Linux 为 Python 网页路线，本轮未做这些系统的实机验收。

## English quick start

Use Python 3.11+ with SQLite FTS5 and a browser. Run `python launch.py`, choose real work, and select your Vault plus optional knowledge directories. Later starts preserve those choices. No global Agent rules, API calls or model downloads are triggered.

Register a project using `python -m memory_hub project --vault /path/to/vault --name Report --path /path/to/project --goal "Review evidence"`. Start with `python -m memory_hub serve --vault /path/to/vault`. Add `--project Report` to close tasks into verified project receipts. Human reviews and lifecycle decisions remain explicit.

The synthetic trial is isolated. External knowledge sources are read only. Optional local ONNX models require their own compatible files and dependencies; unavailable models fall back explicitly to lexical retrieval. Raw Agent logs and attachments are not automatically ingested.

Stop before upgrading. Back up the Vault and local-settings.json, then run the verified updater described above. It preserves user state and creates a source rollback backup. Local source customizations require manual merging. Windows browser operation is tested; macOS/Linux and all new operations in the old Windows desktop observer do not yet have equivalent hardware acceptance.

# Continuous workbench / 连续工作台

The public core now includes evidence-backed project briefs, continuation packets, automatic next-step suggestions, versioned deliveries and human feedback, reversible pause/archive/restore, and natural-language knowledge retrieval.

当前包含可信摘要、接续、自动建议、成果与反馈、归档恢复及自然语言检索。真实部署接入已连接公开版记忆流程，详见 [正式本地部署](local-workbench.md)。原 Windows 桌面观察器保持原有边界；新增操作的完整验收对象是网页工作台。

Independent synthetic trial: `python scripts/demo_server.py --port 8897`, then open http://127.0.0.1:8897/full/index.html . This trial creates only demo-data and does not connect private Vaults. It is not yet the real-data deployment entry.

基本文字召回无需模型。离线语义与重排需要使用者自己的本地模型与可选依赖；本仓库不包含权重、真实库、个人配置或工作日志。UI 当前为中文，README 的语言切换不代表 UI 全面国际化。

Test: `python -m unittest discover -s tests -v`. Tests tied to the author's private configuration are intentionally not exported; public regressions use temporary synthetic files instead.

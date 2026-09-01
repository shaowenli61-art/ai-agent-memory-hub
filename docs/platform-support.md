# 平台支持边界

| 组件 | Windows 10/11 | macOS | 说明 |
|---|---:|---:|---|
| Python CLI | 支持 | 支持 | Python 3.11+ |
| Obsidian Vault | 支持 | 支持 | Obsidian 推荐但不是生成 Markdown 的硬依赖 |
| 网页工作台 | 支持 | 支持 | 使用本机浏览器和本地 HTTP 服务 |
| 桌面工作台 | 支持 | 不支持 | WPF + WebView2，仅构建 `win-x64` |

macOS 用户选择 `web` 或 `none`。部署计划在 macOS 上选择 `desktop` 时会直接拒绝，而不是静默降级。

Windows 桌面端需要 .NET 9 SDK（构建时）和 WebView2 Runtime（运行时）。部署 Agent 应先检查，再向用户说明缺口和安装来源；不能因为缺少桌面依赖而阻断核心或网页工作台。

# 第三方说明

本包核心业务源码、fixture、测试和界面为本次开发新写。没有整体 fork、复制 OpenHands、Open SWE、DeerFlow、DeepSeek Harness 或 Full Stack FastAPI Template 的源码。它们是目标集成或架构参考，不应将其上游能力记为本项目已实现。

实际使用 Python 依赖以 pyproject.toml / reports/environment.json 为准；前端候选依赖以 frontend/package.json 为准，未随包打入 node_modules。所有依赖保留自身许可证，正式发布前需根据最终锁文件生成 SBOM 与许可证清单。未附带字体文件。

本包没有代替项目所有者决定开源许可证。公开发布前在 LICENSE 中选定许可，并审查所有依赖与资料使用权限。

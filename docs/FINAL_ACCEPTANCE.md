# 本轮最终修复验收（以本页及关联原始证据为准）

本页更新之前的阶段性验收记录。已验证代码提交：`911041016a817c26e6a6decd35f79657c9ff892e`。本页为其后的纯文档提交，不将未完成的再次 CI 自动视为成功。

仓库：`volcano-code/TraceForge`；修复分支：`fix/m2-hardening-20260929`；草稿 PR：[#1](https://github.com/volcano-code/TraceForge/pull/1)。main 未合并。原 M2-start 附件未改动。源码为可直接克隆、审阅的独立文件。

## 实测结果

完整质量流水线：[36466029302](https://github.com/volcano-code/TraceForge/actions/runs/36466029302)，backend / frontend / postgres 全部成功。

独立 rootless Docker 实机流水线：[36466029275](https://github.com/volcano-code/TraceForge/actions/runs/36466029275)，成功。

| 项目 | 实际结果与限制 |
|---|---|
| Python | 下载并解析 JUnit：180 tests，0 failures，0 errors，0 skipped |
| Node | 23 个协议／事件流测试通过 |
| React | 完整 TypeScript 检查、Vite 生产构建通过；有真实 package-lock.json |
| Vitest | API 边界单元测试通过，排除 Playwright 文件 |
| Chromium | 1 个真实浏览器冒烟测试通过：认证与 fixture 项目列表，不是完整审批流程 |
| PostgreSQL | 1 个组合实机集成测试通过：临时 schema、迁移、同键并发创建、唯一领取、fixture 验证、本地幂等交付；不是全面压力或灾备验收 |
| HTTP + 独立 Worker | 13 个检查通过 |
| 模拟交付 | 6 个故障场景通过；不是实际 GitHub exactly-once 证明 |
| rootless Docker | 1 个集成测试内完成 6 次受控样例容器执行（3 个缺陷各 before/after）；全部通过；不使用宿主执行回退 |

Docker 原始记录：`rootless-live-evidence/live-docker-diagnostics.json`：`status=PASS`，`containers_executed=6`，所有 check.passed=true，`real_model_called=false`，`arbitrary_repository_tested=false`。

实测 Docker server 29.8.1，rootless，cgroup v2/systemd，CPU／内存／swap／PID 控制预检通过。实际使用的缓存镜像 ID：`sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b`。网络关闭，输入与根文件系统只读，无 host fallback。

## 原始证据

同一代码提交的 Actions artifacts：

- backend-evidence：10989313704；ZIP SHA256 `bf108e7b6708700f4abdfa6db32cd298f3eb30e13bec695de4878f89f8706ea9`。
- frontend-evidence-and-lock：10988734109；ZIP SHA256 `336442f4b9a0aac01d8c3d29e67b8c5cf8eabe3638ab614b3d66aee180ee9d98`。
- postgres-evidence：10989752700；ZIP SHA256 `74822950c4d790dc5c26e42d22d1b18f01b0d5d5f2222158ecd29f4bdea602bd`。
- rootless-live-evidence：10989043600；ZIP SHA256 `f71cab0dc2de5ac24870599da85871950f4cc132b5125b916456424058d364fc`。

Artifact 由 GitHub 按保留期保存，不是永久存档。SHA256 不构成独立数字签名或来源真实性保证。

## 本轮关闭的缺陷

- rootless 预检没有检查资源控制，且错误地把预检视为实机验收。
- 子进程创建前缺少授权检查；过期租约仍能续租；Run / Outbox 加锁次序不统一。
- React 事件流的断线续读、序号和归属检查、认证失败停止处理不足。
- Vitest 与 Playwright 测试发现混杂，缺少前置条件会跳过 E2E。
- 新 Compose 环境缺少数据库密码初始化。
- hosted runner 上 `/proc` 进程退出观察竞态；新增两项回归，不删除终止断言。
- 官方 rootless 前置依赖缺失及 apt 安装候选检测错误。
- Docker 29 返回小写 `error: no such object` 导致已删除容器被误报；旧子串匹配又可能误认其他对象。现使用大小写归一化、严格匹配当前容器的缺失回执；新增 12 项回归。连接错误、其他对象和未完成执行仍拒绝放行。

## 不能从这些结果推导的结论

本轮修复和上述限定集成门槛通过，不等于完整 M2 或四周 MVP 完成。真实 OpenHands / DSH / LangGraph / MCP 集成、LLM 工具循环和产品 GitHub App / PR 交付仍未实现。PR #1 是本次代码上传产生，不是 TraceForge 产品能力演示。

六次固定样例容器执行不构成恶意仓库逃逸、资源耗尽攻击、任意代码安全或全系统零缺陷证明。运行时 `doctor` 仍无认证、持久化验收记录，因此不自动宣称 `coding_agent_ready=true`。不放宽主机安全策略，不允许危险宿主回退，不自动 merge 或部署。

旧的 166 / 168 测试报告是过程历史。最后一次额外本地全量复跑超时，未计为通过；最终 180 结果来自上述干净 hosted runner 的 JUnit。未重新计算覆盖率，不引用旧覆盖率冒充当前数据。

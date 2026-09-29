# M2-start 修复与 GitHub 交付

## 边界

本次版本为 `0.3.1.dev0`，修复基础来自 `TraceForge-v0.3.0-M2-start.zip`，原包 SHA256：`8cf8f299b6619cbee331a29afc584db89b938c3fb590f747ea332bf757c7a9f5`。原附件未改动，源码已上传 `fix/m2-hardening-20260929`，PR #1 为草稿，main 未合并。它不是完整 M2 或四周 MVP。

## 实际修复

1. Docker rootless 预检增加 cgroup v2、systemd、CPU、内存、swap 与 PID 控制检查；缺失即拒绝，不回退宿主执行。
2. 能力预检不能消除实机验收阻塞；尚未实现持久、认证的验收记录，因此 readiness 继续保留限制。
3. 创建进程前检查取消／授权，检查异常时不启动进程。
4. Run → Outbox 统一加锁顺序、刷新锁定对象，拒绝过期租约续租与结果发布。
5. React SSE 支持游标续读、断线重试、运行归属与序号检查；退出和认证失败后停止连接。
6. 分离 Vitest 与 Playwright 的测试发现；明确要求的 E2E 前置条件缺失时失败，不标跳过通过。
7. 新本地环境生成 Compose 使用的 PostgreSQL 密码，不覆盖已有 .env。
8. Hosted runner 暴露的 `/proc` 清理探测竞态已修复：普通子进程在读取过程中消失，应判断为已停止；增加两项回归，未删除终止子进程断言。
9. 通过 hosted runner 真正解析、提交 npm 锁文件，后续 CI 使用 npm ci。
10. Rootless CI 显式安装官方缺失依赖并检查 apt 候选，保留环境诊断；不放宽主机安全策略。

## 已完成的实际验证

通过的完整 hosted 质量流水线：
https://github.com/volcano-code/TraceForge/actions/runs/36464385202

对应提交：`350a2058e1725887813dd071d01a5f1f5366e53a`。后续代码变化及独立 Docker gate 以最新 Actions 为准。

| 检查 | 实际结果和范围 |
|---|---|
| Python | 168 通过，0 失败、错误、跳过；已下载 JUnit |
| Node | 23 项协议／事件流测试通过 |
| React | TypeScript 完整检查与 Vite 生产构建通过 |
| Vitest | API 边界单元测试通过 |
| Chromium | 1 项 Playwright 冒烟通过：认证和 fixture 项目列表；不是完整浏览器工作流 |
| PostgreSQL | 1 项真实集成通过：临时 schema、迁移、并发同键创建、唯一领取、fixture 验证、幂等本地交付 |
| HTTP + Worker | 13 项检查通过，独立进程真实请求 |
| 模拟交付 | 6 个可靠性场景通过；不是 GitHub exactly-once 证明 |

最初的 hosted 后端运行确实失败过（165 通过、1 个进程清理探测竞态失败）。修复后完整重跑通过，保留失败历史。

`reports/repair/summary.json` 是上传前本地 166 项测试的历史快照，不是当前最终成绩。没有重新计算覆盖率，不复用旧覆盖率冒充本轮数据。正式证据在 Actions 的 backend-evidence、frontend-evidence-and-lock、postgres-evidence 和 rootless-live-evidence 中。

## 仍未完成

Rootless Docker 为独立显式实机门槛，不从默认质量流水线成功推断其通过；其实际结果见 `.github/workflows/rootless-gate.yml` 的运行日志。即使六个固定样例容器通过，也不等于恶意代码逃逸测试、资源耗尽攻击验收或通用隔离认证。

真实 OpenHands／DSH／LangGraph／MCP 集成、模型工具循环及产品 GitHub App／真实 PR 交付尚未实现。原生和 React 界面现在都可供本地开发，但不可因此对公网开放任意仓库执行。由 ChatGPT 创建 PR #1 是代码发布操作，不是 TraceForge 自动创建 PR 的演示。

## 官方参考

- https://docs.docker.com/engine/security/rootless/
- https://docs.docker.com/engine/install/ubuntu/
- https://v3.vitest.dev/config/
- https://docs.sqlalchemy.org/en/20/orm/session_api.html

不通过的验收不能改成 skip/pass 来让 CI 变绿。

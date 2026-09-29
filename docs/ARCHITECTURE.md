> **M1 更新：** 本轮实现与当前验收以 [M1_DELIVERY.md](M1_DELIVERY.md)、ADR 004–006、`reports/m1/` 为准；下面保留 M0 基线说明，不将旧数字当作本轮成绩。

# M0 架构与目标架构

## 当前实际实现

```text
原生 HTML/JS 工作台 / React 源码
          │ Bearer + REST + SSE
          ▼
FastAPI → Services → SQLite / SQLAlchemy
                   ├─ Run + Event + Outbox（同事务）
                   ├─ Approval / Operation
                   └─ Content-addressed Artifacts
                               ▲
独立 Worker 进程 → DB 租约 → 固定 fixture 执行器
                         ├─ Git 工作区
                         ├─ 已知补丁
                         └─ 另一 clean checkout + 独立 grader
```

状态机为 `QUEUED → PREPARING → REPRODUCING → PATCHING → VERIFYING → WAITING_APPROVAL → APPROVED → DELIVERED_LOCAL`，另有 FAILED/CANCELLED/REJECTED。每个提交后的阶段可恢复；这是数据库状态机，不是 LangGraph。单步副作用可能重跑；目前只在受控 fixture 上验证重入和 DB 写入 fencing。

## 数据与一致性

八张业务表：projects、webhook_receipts、runs、approvals、artifacts、outbox_events、run_events、operations。精确字段、索引与约束见 `contracts/database-tables.json` 和 Alembic migration。

Run/Outbox 一起写入，避免先返回任务再遗漏派发。SQLite 使用 WAL、foreign_keys、busy_timeout 与 BEGIN IMMEDIATE；网络和子进程执行不持有数据库写锁。Outbox 租约令牌防止旧 Worker 提交新状态。PostgreSQL 代码路径与 Compose 是待验证候选，不声称已解决其所有锁竞争；必须添加并发事务、死锁与 lease fencing 集成测试。

事件按 `(run_id, sequence)` 唯一递增，并保留 state_version。SSE 使用 Last-Event-ID 或 after_seq 重读持久化事件，不把浏览器内存当业务真相。当前事件日志不等于完整 event sourcing，业务状态仍保存在 runs。

制品按 SHA256 内容寻址，读取时重新检查哈希与长度；审批绑定 base_commit、patch_hash、validation_digest。审批与交付再次检查证据，本地交付回执与操作记录同事务，重复请求返回同一操作。它不是对外部 GitHub API 的 exactly-once 保证。

## 目标分层（尚未完成）

LangGraph 管 Prepare/Reproduce/Fix/Verify/Review 等业务阶段；OpenHands SDK 或 DSH 管阶段内部工具循环，同一任务只能选择一个执行器。Celery/Redis 接收 Outbox 派发，不成为任务状态真相。MCP 是工具连接；A2A 是独立 QA Agent 委派；AG-UI 是前端事件适配。任何协议不提供免审批写权限。

`CodeExecutor` 后续合同为 start / execute / stream_events / interrupt / snapshot / close。接入时先做 SDK + tools 同版本安装与沙箱兼容性试验，不能把文档中的宿主机 Shell 示例直接当成安全生产实现。

## 目标信任边界

可信控制服务保存审批、GitHub 写凭据、评分规则和操作账本。Agent 只拿临时工作区、任务范围和有限工具。验证服务重新 clean checkout、应用已批准候选补丁，并在另一个隔离执行环境运行测试；测试本身会执行不可信代码，因此“可信评分器”不表示可以在宿主上安全运行任意仓库。

本 M0 不具备上述恶意代码隔离，采用严格已知代码字节 allowlist；不允许用它接入外部任意仓库。

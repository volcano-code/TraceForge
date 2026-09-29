# TraceForge v0.2.0-M1 · 本轮开发交付

本轮在上传的 M0 代码的独立副本上继续开发，保留原始压缩包。遵循最新从零规划确定的核心方向，不声称已经完成所有阶段。本轮没有推送 GitHub、创建真实 PR、调用真实模型或修改用户电脑。

## 本轮新增

| 模块 | 已实现与测试的功能 |
|---|---|
| EvidenceInspector | 完整制品引用、任务归属、哈希、前后结果、可信 grader 哈希、环境指纹；完整 JSON 导出与只读离线校验 |
| Action-scoped Approval | 审批绑定基线、补丁、验证报告和交付范围；本地回执与模拟提交不能复用错误范围的批准 |
| DeliveryService | 在外部请求前持久化操作；结果分类为 EXECUTING / IN_DOUBT / SUCCEEDED / BLOCKED；只读核实不盲目重发 |
| Independent simulator | 不同 SQLite 数据库和事务，真实持久化模拟端动作与调用次数；不是 GitHub |
| Recovery / fencing | 同任务并发与重放返回同一操作；旧租约结果不能覆盖新核实结果；未核实的提交不能假装取消 |
| API / UI | 证据查看、导出、操作列表、范围选择、模拟提交和核实；React 源码已更新但未完整构建 |
| Migration | M0 升级保留旧数据；有模拟交付历史时拒绝破坏恢复语义的降级 |

## 本轮实际验证

| 项目 | 结果 |
|---|---|
| 原 M0 基线重跑 | 61 项通过 |
| 更新后的 Python 全量测试 | 92 项通过，0 失败，0 错误，0 跳过；比基线新增31项 |
| 后端语句覆盖率 | 1047/1111，94.24%；不包括 CLI/Worker 入口，不是整个系统覆盖率 |
| Node 协议测试 | 15 项通过；不是 Vitest |
| TypeScript 语法检查 | 9 文件、0 语法错误；不是完整类型检查或生产构建 |
| 真实 HTTP + 独立 Worker | 13 项检查通过，含 SSE 续读、独立验证、审批、模拟交付和证据导出 |
| 故障实验 | 6 场景通过：正常、丢响应、提交后进程退出、未观察到结果、基线改变、查询不确定 |
| Chromium 浏览器验收 | 已尝试但被 ERR_BLOCKED_BY_ADMINISTRATOR 阻断；0 个浏览器检查通过，没有本轮截图 |

故障实验中的崩溃是**独立 Python 子进程实际退出**；为了可重复测试，恢复前显式使租约到期。在已提交的模拟场景中，提交调用次数为1、持久化动作数为1；未观察到结果时保持 IN_DOUBT，不自动重发。该结果不证明真实 GitHub exactly-once，不代表生产环境通用事务保证。

## 最快复现

需要 Python 和 Git。Python 实测版本3.13.5，首次依赖安装需要网络。

```bash
cd traceforge
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python scripts/reliability_demo.py
python scripts/http_smoke_m1.py
python -m traceforge.cli verify-bundle reports/m1/evidence-bundle.json
```

启动工作台：

```bash
python scripts/bootstrap.py
python -m traceforge.cli init
python scripts/dev.py
```

浏览器打开 `http://127.0.0.1:8000/workbench`，使用本地 `.env` 中的 `TF_REVIEWER_TOKEN`。不要把令牌上传 GitHub 或贴到聊天。基础演示不需要模型密钥或 GitHub 授权。

## 下载包中重点文件

`src/traceforge/evidence.py`、`src/traceforge/delivery/`、`migrations/versions/b82f4b61d2a0_delivery_operation_recovery.py`、`tests/test_evidence_m1.py`、`tests/test_delivery_m1.py`、`tests/test_migration_m1.py`、`scripts/reliability_demo.py`、`scripts/http_smoke_m1.py`、`reports/m1/verification.json`、`docs/M1_DELIVERY.md`、`planning/ISSUES_M1.md`。

`reports/m0/` 只保留历史记录；`reports/m1/` 才是本轮结果。`examples/m1-executed-fixture/` 内是这轮真实受控执行产生的补丁、测试、事件和回执。

## 边界与下一验收关口

当前仍只有包内三个已知缺陷和确定性补丁执行器，**未接入自主 Coding Agent**。SHA256 校验不是数字签名，不证明记录来源不可伪造。审计接口检查已记录证据，不会重新跑测试或代替执行时的授权检查。

React 依赖安装被 npm DNS 问题阻塞；浏览器测试被管理策略阻断；Docker 不存在；PostgreSQL、OpenHands、LangGraph、DSH、MCP/A2A/AG-UI、真实模型和真实 GitHub PR 均未验收。真实 `/deliveries/pr` 仍明确失败关闭。没有通用回滚能力，不允许导入任意不可信仓库或开放公网服务。

下一批应优先完成可隔离的执行环境、React 构建与浏览器验证、真实执行器工具循环，之后才接入授权仓库和真实 PR；不以增加新的框架名称替代验收。

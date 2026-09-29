> 本轮状态：M1 严格复核修复通过；M2-start 执行边界起步，**不是整期 MVP 完成**。见 `AUDIT_M1.md`、`M2_EXECUTION.md` 与最新 `reports/m2-start/verification.json`。Linux/WSL2 是本地执行验收平台。

> **M1 更新：** 本轮实现与当前验收以 [M1_DELIVERY.md](M1_DELIVERY.md)、ADR 004–006、`reports/m1/` 为准；下面保留 M0 基线说明，不将旧数字当作本轮成绩。

# 本次实际验收记录 · M0

日期：2026-09-22。测试运行于当前 Linux 容器；不代表用户电脑已安装或公网服务已部署。

| 检查 | 结果 | 证据 |
|---|---|---|
| Python pytest | **61 passed**，exit code 0 | reports/backend-test.log、backend-result.json、backend-junit.xml |
| Python语句覆盖 | **707/740 = 95.54%** | reports/coverage.json；仅列出的后端模块，排除CLI/Worker入口；不是分支或系统覆盖率 |
| JavaScript协议 | **13 passed / 0 failed** | reports/frontend-protocol-test.log；Node原生测试，不是Vitest |
| TypeScript语法 | **9个文件、0个语法错误** | reports/typescript-syntax.log；不是完整类型检查/构建 |
| 真实HTTP链路 | **10项检查通过** | reports/http-smoke.json；真实API与独立Worker进程 |
| 数据库迁移 | SQLite upgrade→downgrade→upgrade→check | 包含在pytest中，不额外重复计数 |
| 本地editable安装 | 成功（使用环境已装依赖，无网络） | reports/editable-install.log |
| OpenAPI | 从实际FastAPI导出 | contracts/openapi.json |
| Docker/PostgreSQL | **NOT_RUN** | 无Docker/psycopg服务环境，仅配置 |
| React完整tsc/Vite/Vitest | **NOT_RUN** | npm DNS受阻；只有源码与语法检查 |
| 浏览器E2E/视觉检查 | **NOT_RUN** | 无Chromium；有Playwright测试源码不能算执行 |
| 真实OpenHands/DSH/模型调用 | **NOT_RUN** | 不存在模型调用费用与模型修复成功率 |
| GitHub App/真实PR | **NOT_RUN** | PR路由503；本地回执real_github_pr_created=false |
| 远程GitHub Actions | **NOT_RUN** | 配置文件不代表远程CI运行 |

## 实際HTTP检查

迁移与样例初始化、TCP健康、静态页面和JS服务、鉴权与项目、任务创建/幂等重放、独立Worker复现/补丁/验证、无批准交付拒绝/开发者审批拒绝、哈希绑定审批和本地回执幂等、真实PR fail-closed、SSE Last-Event-ID续读。结果是15条连续事件、5个制品，终态DELIVERED_LOCAL。

## 边界

三个fixture为公开已知缺陷，四项unittest与独立clean checkout均真实运行。补丁是预写oracle，不是Agent生成。证据包可信范围只是这些受控执行，不证明任意仓库代码安全或所有缺陷正确。61不是业务缺陷数，95.54%不是模型成功率。

安全测试覆盖当前认证/审批/哈希/路径/重放边界，不含真实模型提示注入ASR。不能把未发生模型调用时的“零越权”当成模型安全能力。

## 尚不满足的里程碑

W1：真实授权仓库与沙箱、PostgreSQL、npm构建；W2：OpenHands/模型/LangGraph；W3：真实PR；W4：冻结Agent评测、另一台机器部署和试用。当前只完成M0基础设施切片。

## 交付包复验

源文件打包后解压到新的临时目录，再运行 `scripts/http_smoke.py`，10项检查全部通过。使用的是同一容器及已安装Python依赖，不是另一台机器或完全无依赖环境复现。记录见 reports/cold-extraction.json。

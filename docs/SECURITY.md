> 本轮状态：M1 严格复核修复通过；M2-start 执行边界起步，**不是整期 MVP 完成**。见 `AUDIT_M1.md`、`M2_EXECUTION.md` 与最新 `reports/m2-start/verification.json`。Linux/WSL2 是本地执行验收平台。

> **M1 更新：** 本轮实现与当前验收以 [M1_DELIVERY.md](M1_DELIVERY.md)、ADR 004–006、`reports/m1/` 为准；下面保留 M0 基线说明，不将旧数字当作本轮成绩。

# 安全范围与已知限制

## 允许使用方式

本版本仅在本机回环地址用于三个预先审阅的 fixture。测试、Git 工作树与补丁均实际运行，但不是 Docker / gVisor / microVM 沙箱。`python -I` 只是 Python 隔离模式，不是 OS 安全边界。

## 已实现并测试

独立 developer/reviewer 开发令牌；空或重复令牌配置拒绝；审批角色由后端判断；补丁、基线、报告三重绑定；审批到期检查；制品哈希检查；只接受已知代码字节；路径和 symlink 检查；限制 Webhook 大小；HMAC 原始字节验签；delivery ID/内容哈希去重；不向模型或子进程传 GitHub 凭据；真实 PR 路由 fail closed。

网页令牌仅内存保存。制品按文本返回并设置 nosniff，不把仓库内容作为可信 HTML。日志 sanitize 是有限正则，不是完整 DLP；未知格式敏感内容仍可能泄漏，接真实仓库前必须加源头过滤与专门测试。

## 不是已经实现的安全能力

没有 GitHub App 安装授权、OAuth 登录、组织级 RBAC、每项目用户隔离、网络出口沙箱、恶意依赖检测、浏览器独立 origin 容器、完整 CSRF/session 策略、密钥轮换服务、生产审计保留策略。

本地 reviewer token 只代表开发角色，不代表可追溯的真实人员身份。所有持有开发令牌的人属于同一个本地项目域；不要对公网开放。TLS 和企业身份认证未接入。Docker 配置的出现不意味着 Docker 已执行，更不意味着任意代码安全。

## 任意仓库接入前的阻塞项

运行环境与控制服务分离；不挂宿主 Docker socket；不传安装令牌/数据库口令；默认限制网络，依赖下载单独授权；验证环境与编码环境隔离；受保护路径和测试规则不可修改；命令预算/资源限额/进程组取消；Workspace fencing 防止租约过期旧进程继续写；补丁/分支改变时重新验证；GitHub 结果不明进入 IN_DOUBT 并 reconcile。

PostgreSQL 真正运行前统一锁获取顺序并测试死锁重试；当前测试仅证明 SQLite 路径。外部写操作不得根据超时直接重试，也不得将安全限制仅写进模型奖励。

测试为零违规只说明列出的案例，不能声明普遍安全或正式认证。

# M2-start：捕获输入与失败关闭执行边界

## 设计与自研内容

`ReviewedInput.capture` 只接受小型普通文件，拒绝符号链接、目录、FIFO 和未审阅字节；读取前后检查 fd 属性，一次捕获 bytes 并与固定源码比对。执行使用捕获内容的新副本，不再读取可能改变的工作区路径。测试器同样来自可信固定字节。每次执行保存源码、grader、输入清单及环境指纹。

这解决的是“校验 A，执行了后续改变的 B”的输入绑定问题，不等于保护宿主免受恶意代码攻击。当前只允许已知公开合成源代码。临时目录与只读文件权限也不防具有同一系统用户权限的恶意进程或 root。

`BoundedProcessRunner` 不启用 Shell，明确 env，不继承模型/GitHub 密钥；使用 POSIX 进程组，限制墙钟时间和输出，执行过程中检查取消和租约，权限检查失败则终止。普通子进程会清理，刻意 setsid 脱离进程组的恶意代码不属于本地模式保证。

固定测试代码命令上限 10 秒、256 KiB 输出，是本项目配置，不是机器性能保证。Git 准备/应用仍是固定命令与原实现；没有宣称整个任意仓库工作区已经具有跨进程资源隔离或 fencing。

## Docker 驱动与边界

必须同时满足：本机 Docker CLI；本地 Unix socket；Docker info 表明 rootless；镜像已缓存且配置为完整 sha256 ID；Linux 镜像；无隐式 VOLUME。任何失败返回明确错误，不创建任务、不下载镜像、不回退宿主。

容器命令：network none、read-only root、UID/GID 65534、drop ALL capabilities、no-new-privileges、private IPC、1 CPU、256 MiB 内存与无额外 swap、64 PID、只读 /input、32 MiB tmpfs。只挂载审阅输入，**不挂载 Docker Socket、源码根目录、控制数据库、令牌或 App 私钥**。

Docker CLI 被杀不等于容器退出；驱动会以随机 name 和 owner label 查询，只清理自己拥有的容器。清理结果不确定则报错，禁止自动再次派发。当前还没有整台宿主断电后的持久化 orphan 收敛服务，这属于下一阶段门槛。

这些是实现与契约测试检查的配置。**本轮环境没有 Docker，实机执行为 0；不能宣称已经验证资源限制、网络隔离、非 root 运行或内核安全。** rootless 也不是对所有内核漏洞或不可信仓库的完整隔离证明。

## 在合适宿主运行实机门槛

使用 Linux/WSL2，先由你本人安装和配置 rootless Docker。官方资料：
- https://docs.docker.com/engine/security/rootless/
- https://docs.docker.com/engine/containers/run/

由操作者提供已审核的缓存 Python stdlib 镜像，或通过 `deploy/fixture-sandbox.Dockerfile` 从操作者指定的固定 digest 基础镜像构建。不要在文档中复制随机 SHA256 占位当成真实镜像。

```bash
# my-reviewed-fixture:local 必须是你已经审核并缓存的 Linux Python 镜像。
export TF_SANDBOX_DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
export TF_SANDBOX_IMAGE_ID="$(docker --host "$TF_SANDBOX_DOCKER_HOST" image inspect my-reviewed-fixture:local --format '{{.Id}}')"
export TF_EXECUTION_BACKEND=docker_fixture
python -m traceforge.cli sandbox-smoke
python -m pytest tests_live/test_docker_gate.py -q
```

命令不会自行安装 Docker/下载镜像。CLI 返回 BLOCKED/FAIL 时不得放行，也不得删掉防护参数来“跑通”。live 测试不在默认 pytest 路径中，必须显式执行；缺环境是 FAIL/BLOCKED 而非 skip/PASS。

即使上述六次 fixture 容器验证成功，也只能说明该机器的这个镜像能够执行受控输入。开放不可信仓库前还必须独立检查网络出口、拒绝宿主/私钥访问、资源上限、运行超时与强制清理、重启 orphan 核实和只读 grader 边界。

## OpenHands 接入状态

`doctor` 查询 SDK/工具/工作空间包版本及本地 Docker 前置条件，**它不是 OpenHands 适配器**。当前 `coding_agent_ready` 固定为 false，并列出未集成执行器、未验证真实模型往返和通用仓库验证器。没有把一个空类或 ready 标志当完成。

官方接口参考：
- https://docs.openhands.dev/sdk/getting-started
- https://docs.openhands.dev/sdk/guides/agent-server/overview

下一关口需要锁定匹配 SDK/工具版本并做真实兼容性测试；模型密钥留在控制平面/受控网关，执行沙箱无 GitHub 写凭据；OpenHands 与 DSH 互为替代执行器，不能叠加双重循环。本轮网络解析阻塞和缺少 Docker 的证据已保存，不伪造 SDK 安装记录。

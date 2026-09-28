# 开发约定

先阅读 README 的真实状态和 docs/SECURITY.md。新增能力必须关联 planning/issues.json 中的任务或补充新任务。

修改后运行 Python 测试、JS 协议测试与 HTTP smoke；涉及 React 时还必须 npm install / build / test / browser E2E。未运行必须写 NOT_RUN，不可因工具不可用写 PASS。

禁止提交 .env、数据库、GitHub App 私钥、真实用户数据和未清洗日志。新 runtime 不允许绕过验证或审批。每次评测绑定模型、提示、技能、工具、环境、任务集与评分器版本；不得使用已知 fixture 结果宣称模型效果。

"""Versioned historical evidence, never authority to execute on the current host."""
from . import __version__


def release_info() -> dict:
    return {
        'version': __version__,
        'stage': 'M2 工程修复与业务验收',
        'current_host_attested': False,
        'coding_agent_ready': False,
        'history': {
            'source_commit': '911041016a817c26e6a6decd35f79657c9ff892e',
            'quality_run_id': 36466029302,
            'rootless_run_id': 36466029275,
            'scope': '历史代码版本的 CI 记录，不是当前主机或当前修改的实时验收',
            'checks': [
                {'name': 'Python', 'result': '180 项通过'},
                {'name': 'Node 协议', 'result': '23 项通过'},
                {'name': 'React / TypeScript / Vite / Vitest', 'result': '构建与测试通过'},
                {'name': 'Chromium', 'result': '1 项登录与项目列表冒烟通过'},
                {'name': 'PostgreSQL', 'result': '1 项组合集成通过'},
                {'name': 'rootless Docker', 'result': '6 次已审阅样例执行通过'},
            ],
        },
        'pending': ['真实模型与 Coding Runtime', '仓库级独立验证', '产品 GitHub App 与真实 PR',
                    '任意仓库隔离与持久化 orphan 恢复'],
    }

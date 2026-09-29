'''Reviewed deterministic fixtures, NOT an autonomous Coding Agent.

The local runner rejects all source bytes except the bundled original/fixed
versions. A subprocess/temporary directory is NOT a hostile-code sandbox.
'''
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from .artifacts import digest
from .domain import DomainError

@dataclass(frozen=True)
class Fixture:
    id: str
    title: str
    objective: str
    original: str
    fixed: str
    test_body: str
    expected_failure: str

PAGINATION='''def paginate(items, page=1, size=2):
    if page < 1 or size < 1:
        raise ValueError("page and size must be positive")
    pages = max(1, (len(items) + size - 1) // size)
    current = page
    start = (current - 1) * size
    return {"items": items[start:start + size], "page": current, "pages": pages, "total": len(items)}
'''
MEAN='''def mean(values):
    return sum(values) / len(values)
'''
SLUG='''def slug(text):
    return text.lower().replace(" ", "-")
'''
FIXTURES={f.id:f for f in [
Fixture("pagination","删除后分页越界","删除末页最后一项后，当前页应收缩到有效末页，不能返回空白页。",PAGINATION,
    PAGINATION.replace("current = page","current = min(page, pages)"),
    '''    def test_delete_last_page(self):
        self.assertEqual(m.paginate([1, 2], page=2), {"items":[1,2],"page":1,"pages":1,"total":2})
    def test_first_page(self):
        self.assertEqual(m.paginate([1,2,3])["items"],[1,2])
    def test_empty(self):
        self.assertEqual(m.paginate([])["items"],[])
    def test_invalid(self):
        with self.assertRaises(ValueError): m.paginate([1],size=0)
''',"test_delete_last_page"),
Fixture("empty-mean","空集合统计错误","空集合平均值应返回 None，普通数值和零值不能回归。",MEAN,
    'def mean(values):\n    return sum(values) / len(values) if values else None\n',
    '''    def test_empty_mean(self):
        try: result = m.mean([])
        except ZeroDivisionError: self.fail("Empty collection raised ZeroDivisionError")
        self.assertIsNone(result)
    def test_regular(self): self.assertEqual(m.mean([2,4]),3)
    def test_zero(self): self.assertEqual(m.mean([0]),0)
    def test_negative(self): self.assertEqual(m.mean([-2,2]),0)
''',"test_empty_mean"),
Fixture("slug-space","多空白归一化错误","Slug 应合并连续空白并去掉首尾空白，保持既有小写和空字符串行为。",SLUG,
    'def slug(text):\n    return "-".join(text.lower().split())\n',
    '''    def test_whitespace(self): self.assertEqual(m.slug("  Hello   World  "),"hello-world")
    def test_plain(self): self.assertEqual(m.slug("Hello World"),"hello-world")
    def test_empty(self): self.assertEqual(m.slug(""),"")
    def test_single(self): self.assertEqual(m.slug("ABC"),"abc")
''',"test_whitespace"),
]}

def fixture(fid: str) -> Fixture:
    if fid not in FIXTURES: raise DomainError("UNKNOWN_FIXTURE","Only bundled fixtures are executable",400)
    return FIXTURES[fid]

def safe_env(home: Path) -> dict[str,str]:
    return {"PATH":os.environ.get("PATH","/usr/bin:/bin"),"HOME":str(home),"LANG":"C.UTF-8",
            "GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":os.devnull,
            "GIT_TERMINAL_PROMPT":"0","GIT_AUTHOR_DATE":"2026-09-22T00:00:00+0000",
            "GIT_COMMITTER_DATE":"2026-09-22T00:00:00+0000"}

def git(cwd: Path, *args: str) -> str:
    result=subprocess.run(["git","-c","core.hooksPath="+os.devnull,*args],cwd=cwd,
        env=safe_env(cwd),capture_output=True,text=True,timeout=15,check=False)
    if result.returncode: raise DomainError("GIT_FAILED","Fixture git operation failed")
    return result.stdout.strip() if args[0] != "diff" else result.stdout

def grader_source(fid: str) -> str:
    spec=fixture(fid)
    runner='''import importlib.util, io, json, sys, unittest
spec = importlib.util.spec_from_file_location("subject", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
class FixtureTests(unittest.TestCase):
'''+spec.test_body+'''
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FixtureTests))
print(json.dumps({"tests_run":result.testsRun,"failures":[t.id().split(".")[-1] for t,_ in result.failures],"errors":[t.id().split(".")[-1] for t,_ in result.errors],"skipped":len(result.skipped),"log":stream.getvalue()}))
sys.exit(0 if result.wasSuccessful() else 1)
'''
    return runner

class WorkspaceManager:
    def __init__(self, root: Path, test_backend=None):
        from .execution.reviewed import ReviewedSubprocessBackend
        self.test_backend=test_backend or ReviewedSubprocessBackend()
        self.root=root.resolve(); (self.root/"origins").mkdir(parents=True,exist_ok=True)
        (self.root/"runs").mkdir(parents=True,exist_ok=True)
    def origin(self, fid: str) -> Path:
        fixture(fid); return self.root/"origins"/fid
    def seed(self, fid: str) -> str:
        spec=fixture(fid); path=self.origin(fid); path.mkdir(parents=True,exist_ok=True)
        if not (path/".git").exists():
            (path/"module.py").write_text(spec.original)
            git(path,"init","--initial-branch=main")
            git(path,"config","user.name","TraceForge Fixture")
            git(path,"config","user.email","fixture@traceforge.invalid")
            git(path,"add","module.py"); git(path,"commit","-m","Reviewed synthetic bug fixture")
        if git(path,"status","--porcelain"):
            raise DomainError("ORIGIN_DIRTY","Bundled origin has uncommitted changes")
        if (path/"module.py").read_text()!=spec.original:
            raise DomainError("ORIGIN_TAMPERED","Bundled source changed")
        return git(path,"rev-parse","HEAD")
    def run_root(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9-]{36}",run_id):
            raise DomainError("INVALID_RUN_ID","Invalid workspace key",400)
        path=self.root/"runs"/run_id
        if path.is_symlink(): raise DomainError("UNSAFE_PATH","Symlink rejected")
        path.mkdir(parents=True,exist_ok=True); return path
    def checkout(self, run_id: str, fid: str, base_commit: str, name: str) -> Path:
        if name not in {"workspace","validator"}: raise ValueError("invalid checkout name")
        parent=self.run_root(run_id); target=parent/name
        if target.is_symlink(): raise DomainError("UNSAFE_PATH","Symlink rejected")
        if target.exists(): shutil.rmtree(target)
        git(parent,"clone","--no-hardlinks",str(self.origin(fid)),str(target))
        git(target,"checkout","--detach",base_commit)
        if git(target,"rev-parse","HEAD")!=base_commit:
            raise DomainError("BASE_MISMATCH","Wrong code version")
        return target
    def workspace(self, run_id: str) -> Path: return self.run_root(run_id)/"workspace"
    def assert_head(self,fid: str,base_commit: str) -> None:
        if git(self.origin(fid),"rev-parse","HEAD")!=base_commit:
            raise DomainError("BASE_CHANGED","Base branch changed; create and verify a new run")
    def test(self,path: Path,fid: str, *, cancelled=None) -> dict:
        from .execution.inputs import ReviewedInput
        # Capture + validate once. Never execute or fingerprint the mutable file again.
        snapshot=ReviewedInput.capture(path/"module.py",fid)
        return self.test_backend.run(snapshot,cancelled=cancelled)

class FixtureExecutor:
    '''Known-good patch oracle for infrastructure tests, never counted as LLM success.'''
    name="fixture"
    def propose(self, workspace: Path, fid: str) -> str:
        spec=fixture(fid); module=workspace/"module.py"
        if module.is_symlink() or module.read_text() not in {spec.original,spec.fixed}:
            raise DomainError("UNTRUSTED_SOURCE","Fixture source was modified outside the approved executor")
        module.write_text(spec.fixed)
        return git(workspace,"diff","--no-ext-diff","--","module.py")

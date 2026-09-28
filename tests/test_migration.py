import os
import subprocess
import sys
from pathlib import Path
from sqlalchemy import create_engine,inspect

def test_fresh_upgrade_downgrade_upgrade(tmp_path):
    root=Path(__file__).resolve().parents[1]
    url="sqlite:///"+str(tmp_path/"migration.sqlite")
    env={**os.environ,"TF_DATABASE_URL":url,"TF_DATA_DIR":str(tmp_path),"PYTHONPATH":str(root/"src")}
    for args in [("upgrade","head"),("downgrade","base"),("upgrade","head"),("check",)]:
        result=subprocess.run([sys.executable,"-m","alembic",*args],cwd=root,env=env,capture_output=True,text=True,timeout=20)
        assert result.returncode==0,result.stderr+result.stdout
    engine=create_engine(url)
    assert {"runs","run_events","outbox_events","approvals","operations"}<=set(inspect(engine).get_table_names())
    engine.dispose()

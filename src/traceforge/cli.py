import argparse
import json
from pathlib import Path
from alembic import command
from alembic.config import Config
from .config import Settings
from .db import Database
from .services import Services

def main() -> None:
    parser=argparse.ArgumentParser(description="TraceForge local development commands")
    parser.add_argument("command",choices=["init","seed","openapi","verify-bundle","doctor","sandbox-smoke"])
    parser.add_argument("file", nargs="?", help="Evidence JSON path for verify-bundle")
    args=parser.parse_args()
    if args.command in {"doctor","sandbox-smoke"}:
        if args.file: parser.error("This command takes no file argument")
        from .execution.readiness import readiness_report
        settings=Settings()
        readiness=readiness_report(settings,probe_docker=True)
        if args.command=="doctor":
            print(json.dumps(readiness,ensure_ascii=False,indent=2))
            raise SystemExit(0 if readiness["coding_agent_ready"] else 2)
        from .execution.smoke import docker_smoke
        report=docker_smoke(settings)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        raise SystemExit(0 if report["status"]=="PASS" else 2)
    if args.command=="verify-bundle":
        if not args.file: parser.error("verify-bundle requires an exported evidence JSON file")
        from .evidence import verify_export_integrity
        from .domain import DomainError
        try:
            result=verify_export_integrity(json.loads(Path(args.file).read_text(encoding="utf-8")))
        except (DomainError, ValueError, OSError, TypeError, KeyError) as error:
            print(json.dumps({"integrity_passed":False,"error":str(error)},ensure_ascii=False))
            raise SystemExit(1)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    if args.file: parser.error("Unexpected file argument")
    settings=Settings();settings.prepare()
    if args.command=="init":
        config=Config("alembic.ini")
        command.upgrade(config,"head")
    if args.command in {"init","seed"}:
        db=Database(settings)
        Services(settings,db).seed();db.close()
        print("Database initialized; 3 trusted synthetic fixture projects available.")
    if args.command=="openapi":
        from .api import create_app
        out=Path("contracts/openapi.json");out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(create_app(settings).openapi(),indent=2,ensure_ascii=False))
        print(out)
if __name__=="__main__": main()

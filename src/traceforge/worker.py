import argparse
import logging
import time
from .config import Settings
from .db import Database
from .services import Services
from .workflow import Worker

def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true",help="Process at most one available job")
    parser.add_argument("--drain",action="store_true",help="Process until no available job remains")
    args=parser.parse_args();settings=Settings();db=Database(settings)
    worker=Worker(Services(settings,db))
    try:
        while True:
            work=worker.execute_one()
            if args.once or (args.drain and not work): break
            if not work: time.sleep(0.5)
    except KeyboardInterrupt: pass
    finally: db.close()
if __name__=="__main__": main()

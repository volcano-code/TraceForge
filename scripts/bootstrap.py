"""Create local development credentials. Does not overwrite an existing .env."""
import os
import secrets
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/".env"
if path.exists():
    print(".env already exists; unchanged.")
else:
    content="\n".join([
      "TF_DATABASE_URL=sqlite:///.traceforge/control.db","TF_DATA_DIR=.traceforge",
      "TF_DEVELOPER_TOKEN="+secrets.token_urlsafe(36),
      "TF_REVIEWER_TOKEN="+secrets.token_urlsafe(36),
      "TF_WEBHOOK_SECRET="+secrets.token_urlsafe(36),
      "POSTGRES_PASSWORD="+secrets.token_urlsafe(36),
      "TF_APPROVAL_TTL_SECONDS=900","TF_LEASE_SECONDS=60",""])
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as f: f.write(content)
    print("Created .env with distinct local developer/reviewer credentials. Keep it private.")
print("Next: python -m traceforge.cli init")

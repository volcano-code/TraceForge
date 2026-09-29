from contextlib import contextmanager
from collections.abc import Iterator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from .config import Settings

class Database:
    def __init__(self, settings: Settings):
        settings.prepare()
        sqlite = settings.database_url.startswith("sqlite")
        self.engine = create_engine(settings.database_url, pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 15} if sqlite else {})
        self.sqlite = sqlite
        if sqlite:
            @event.listens_for(self.engine, "connect")
            def sqlite_settings(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.session() as session:
            try:
                # Small control-plane transactions only. Never hold this during tool execution.
                if self.sqlite:
                    session.execute(text("BEGIN IMMEDIATE"))
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def close(self) -> None: self.engine.dispose()

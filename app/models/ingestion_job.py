from datetime import datetime

from pydantic import BaseModel


class IngestionJob(BaseModel):
    id: str
    source_file: str
    source_hash: str | None = None
    status: str
    started_at: datetime
    completed_at: datetime | None = None

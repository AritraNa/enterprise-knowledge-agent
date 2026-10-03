from datetime import datetime

from pydantic import BaseModel


class IngestionJob(BaseModel):
    id: str
    source_file: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None

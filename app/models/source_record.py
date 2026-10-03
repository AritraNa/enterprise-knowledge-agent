from pydantic import BaseModel


class SourceRecord(BaseModel):
    id: str
    source_file: str
    sheet_name: str
    row_number: int

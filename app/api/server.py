import os
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.graph.neo4j_client import Neo4jStore
from app.graph.repository import EmployeeRepository, IngestionJobRepository
from app.ingestion.employee_importer import EmployeeImporter
from app.ingestion.policy_pdf_importer import PolicyPDFImporter
from app.retrieval.employee_vector_store import EmployeeVectorStore
from app.retrieval.policy_vector_store import PolicyVectorStore
from app.workflows.employee_rag import EmployeeRAGWorkflow
from app.workflows.policy_rag import PolicyRAGWorkflow


load_dotenv()

EMPLOYEE_INDEX_PATH = "data/vector_store/employees"
POLICY_INDEX_PATH = "data/vector_store/policies"
POLICY_UPLOAD_DIR = Path("data/uploads/policies")
EMPLOYEE_UPLOAD_DIR = Path("data/uploads/employees")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

app = FastAPI(
    title="Enterprise Knowledge Agent API",
    version="0.1.0",
    description="Upload, search, and ask questions over enterprise policy and employee data.",
)


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    content: str
    distance: float
    source_document: str
    section: str
    page: int | None = None
    metadata: dict[str, str | int | None]


class SearchResponse(BaseModel):
    collection: Literal["policies", "employees"]
    results: list[SearchResult]


class Citation(BaseModel):
    citation_id: int
    source_document: str
    section: str
    page: int | None = None


class AskResponse(BaseModel):
    collection: Literal["policies", "employees"]
    answer: str
    citations: list[Citation]


class IngestResponse(BaseModel):
    collection: Literal["policies", "employees"]
    filename: str
    stored_path: str
    records_indexed: int


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/policies/upload",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_policy(
    file: Annotated[UploadFile, File(description="A policy PDF")],
) -> IngestResponse:
    stored_path, original_name = await _save_upload(
        file, POLICY_UPLOAD_DIR, {".pdf"}
    )
    try:
        records_indexed = await run_in_threadpool(
            _ingest_policy, stored_path, original_name
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to ingest the policy PDF: {error}",
        ) from error

    return IngestResponse(
        collection="policies",
        filename=original_name,
        stored_path=str(stored_path),
        records_indexed=records_indexed,
    )


@app.post(
    "/v1/employees/upload",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_employees(
    file: Annotated[UploadFile, File(description="An employee .xlsx spreadsheet")],
) -> IngestResponse:
    stored_path, original_name = await _save_upload(
        file, EMPLOYEE_UPLOAD_DIR, {".xlsx"}
    )
    try:
        records_indexed = await run_in_threadpool(_ingest_employees, stored_path)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to ingest the employee spreadsheet: {error}",
        ) from error

    return IngestResponse(
        collection="employees",
        filename=original_name,
        stored_path=str(stored_path),
        records_indexed=records_indexed,
    )


@app.post("/v1/policies/search", response_model=SearchResponse)
def search_policies(request: QueryRequest) -> SearchResponse:
    results = PolicyVectorStore(POLICY_INDEX_PATH).search_with_scores(
        request.query, request.limit
    )
    return SearchResponse(
        collection="policies",
        results=[_policy_search_result(document, distance) for document, distance in results],
    )


@app.post("/v1/employees/search", response_model=SearchResponse)
def search_employees(request: QueryRequest) -> SearchResponse:
    results = EmployeeVectorStore(EMPLOYEE_INDEX_PATH).search_with_scores(
        request.query, request.limit
    )
    return SearchResponse(
        collection="employees",
        results=[_employee_search_result(document, distance) for document, distance in results],
    )


@app.post("/v1/policies/ask", response_model=AskResponse)
def ask_policies(request: QueryRequest) -> AskResponse:
    try:
        result = PolicyRAGWorkflow().ask(request.query, request.limit)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Policy answer service is unavailable: {error}",
        ) from error
    return _ask_response("policies", result)


@app.post("/v1/employees/ask", response_model=AskResponse)
def ask_employees(request: QueryRequest) -> AskResponse:
    try:
        result = EmployeeRAGWorkflow().ask(request.query, request.limit)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Employee answer service is unavailable: {error}",
        ) from error
    return _ask_response("employees", result)


async def _save_upload(
    file: UploadFile, destination_dir: Path, allowed_extensions: set[str]
) -> tuple[Path, str]:
    original_name = Path(file.filename or "upload").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Supported file types: {', '.join(sorted(allowed_extensions))}",
        )

    destination_dir.mkdir(parents=True, exist_ok=True)
    stored_path = destination_dir / f"{uuid4().hex}{suffix}"
    bytes_written = 0

    try:
        with stored_path.open("wb") as output:
            while chunk := await file.read(1_024 * 1_024):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Upload exceeds the {MAX_UPLOAD_BYTES} byte limit.",
                    )
                output.write(chunk)
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return stored_path, original_name


def _ingest_policy(path: Path, source_name: str) -> int:
    chunks = PolicyPDFImporter().load(path, source_name=source_name)
    PolicyVectorStore(POLICY_INDEX_PATH).replace_source(chunks)
    return len(chunks)


def _ingest_employees(path: Path) -> int:
    store = Neo4jStore()
    try:
        store.verify()
        store.init_schema()
        importer = EmployeeImporter(
            EmployeeRepository(store.driver),
            IngestionJobRepository(store.driver),
            EmployeeVectorStore(EMPLOYEE_INDEX_PATH),
        )
        return importer.import_file(str(path))
    finally:
        store.close()


def _policy_search_result(document, distance: float) -> SearchResult:
    metadata = document.metadata
    return SearchResult(
        content=document.page_content,
        distance=float(distance),
        source_document=metadata["source_document"],
        section=metadata["section"],
        page=metadata["page"],
        metadata=metadata,
    )


def _employee_search_result(document, distance: float) -> SearchResult:
    metadata = document.metadata
    name = document.page_content.splitlines()[0].removeprefix("Employee: ")
    return SearchResult(
        content=document.page_content,
        distance=float(distance),
        source_document="Employee directory",
        section=f"Employee record: {name} ({metadata['employee_id']})",
        metadata=metadata,
    )


def _ask_response(
    collection: Literal["policies", "employees"], result: dict
) -> AskResponse:
    return AskResponse(
        collection=collection,
        answer=result["answer"],
        citations=[
            Citation(
                citation_id=item["citation_id"],
                source_document=item["source_document"],
                section=item["section"],
                page=item["page"] or None,
            )
            for item in result["citations"]
        ],
    )

import os
import secrets
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.graph.neo4j_client import Neo4jStore
from app.graph.repository import EmployeeRepository, IngestionJobRepository
from app.ingestion.employee_importer import EmployeeImporter
from app.ingestion.policy_pdf_importer import PolicyPDFImporter
from app.retrieval.employee_vector_store import EmployeeVectorStore
from app.retrieval.policy_vector_store import PolicyVectorStore
from app.workflows.employee_rag import EmployeeRAGWorkflow
from app.workflows.compliance_review import ComplianceReviewWorkflow
from app.workflows.policy_rag import PolicyRAGWorkflow

load_dotenv()

POLICY_UPLOAD_DIR = Path("data/uploads/policies")
EMPLOYEE_UPLOAD_DIR = Path("data/uploads/employees")
COMPLIANCE_UPLOAD_DIR = Path("data/uploads/compliance-reviews")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

app = FastAPI(
    title="Enterprise Knowledge Agent API",
    version="0.1.0",
    description="Upload, search, and ask questions over enterprise policy and employee data.",
)

app.mount("/ui", StaticFiles(directory="app/web/static", html=True), name="ui")

# These shared stores reuse the Neo4j driver and Ollama embedding client.
_policy_vector_store = PolicyVectorStore()
_employee_vector_store = EmployeeVectorStore()
_policy_workflow = PolicyRAGWorkflow(vector_store=_policy_vector_store)
_employee_workflow = EmployeeRAGWorkflow(vector_store=_employee_vector_store)
_compliance_workflow = ComplianceReviewWorkflow(vector_store=_policy_vector_store)


@app.on_event("shutdown")
def close_vector_store_drivers() -> None:
    _policy_vector_store.driver.close()
    _employee_vector_store.driver.close()


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=5, ge=1, le=100)


class PolicyQueryRequest(QueryRequest):
    policy_type: str | None = None
    owner_department: str | None = None
    status: str | None = "active"
    effective_date: str | None = None


class EmployeeQueryRequest(QueryRequest):
    department: str | None = None
    location: str | None = None
    job_title: str | None = None
    skills: list[str] = Field(default_factory=list)
    min_experience_years: float | None = Field(default=None, ge=0)


class SearchResult(BaseModel):
    content: str
    score: float
    source_document: str
    section: str
    page: int | None = None
    metadata: dict[str, str | int | float | list[str] | None]


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


class ComplianceReviewResponse(BaseModel):
    document_name: str
    assessment: str
    citations: list[Citation]


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
    policy_type: Annotated[str | None, Form()] = None,
    owner_department: Annotated[str | None, Form()] = None,
    effective_date: Annotated[str | None, Form()] = None,
    version: Annotated[str | None, Form()] = None,
) -> IngestResponse:
    stored_path, original_name = await _save_upload(file, POLICY_UPLOAD_DIR, {".pdf"})
    try:
        records_indexed = await run_in_threadpool(
            _ingest_policy,
            stored_path,
            original_name,
            policy_type,
            owner_department,
            effective_date,
            version,
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
def search_policies(request: PolicyQueryRequest) -> SearchResponse:
    results = _policy_vector_store.search_with_scores(
        request.query,
        request.limit,
        filters={
            "policy_type": request.policy_type,
            "owner_department": request.owner_department,
            "effective_date": request.effective_date,
            "status": request.status,
        },
    )
    return SearchResponse(
        collection="policies",
        results=[_policy_search_result(document, score) for document, score in results],
    )


@app.post("/v1/employees/search", response_model=SearchResponse)
def search_employees(
    request: EmployeeQueryRequest,
    x_api_key: Annotated[str | None, Header()] = None,
) -> SearchResponse:
    include_sensitive = _can_view_sensitive_employee_data(x_api_key)
    results = _employee_vector_store.search_with_scores(
        request.query,
        request.limit,
        filters=_employee_filters(request),
        include_sensitive=include_sensitive,
    )
    return SearchResponse(
        collection="employees",
        results=[
            _employee_search_result(document, score) for document, score in results
        ],
    )


@app.post("/v1/policies/ask", response_model=AskResponse)
def ask_policies(request: PolicyQueryRequest) -> AskResponse:
    try:
        result = _policy_workflow.ask(
            request.query,
            request.limit,
            filters={
                "policy_type": request.policy_type,
                "owner_department": request.owner_department,
                "effective_date": request.effective_date,
                "status": request.status,
            },
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Policy answer service is unavailable: {error}",
        ) from error
    return _ask_response("policies", result)


@app.post("/v1/compliance/review", response_model=ComplianceReviewResponse)
async def review_compliance_document(
    file: Annotated[UploadFile, File(description="A document to compare with indexed policy PDFs")],
    instructions: Annotated[str | None, Form()] = None,
) -> ComplianceReviewResponse:
    stored_path, original_name = await _save_upload(
        file, COMPLIANCE_UPLOAD_DIR, {".pdf"}
    )
    try:
        candidate_chunks = await run_in_threadpool(
            PolicyPDFImporter().load, stored_path, original_name
        )
        result = await run_in_threadpool(
            _compliance_workflow.review,
            original_name,
            candidate_chunks,
            instructions or "",
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to review the uploaded PDF: {error}",
        ) from error

    return ComplianceReviewResponse(
        document_name=original_name,
        assessment=result["assessment"],
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


@app.post("/v1/employees/ask", response_model=AskResponse)
def ask_employees(
    request: EmployeeQueryRequest,
    x_api_key: Annotated[str | None, Header()] = None,
) -> AskResponse:
    try:
        filters = _employee_filters(request)
        filters["include_sensitive"] = _can_view_sensitive_employee_data(x_api_key)
        result = _employee_workflow.ask(request.query, request.limit, filters=filters)
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


def _ingest_policy(
    path: Path,
    source_name: str,
    policy_type: str | None = None,
    owner_department: str | None = None,
    effective_date: str | None = None,
    version: str | None = None,
) -> int:
    chunks = PolicyPDFImporter().load(path, source_name=source_name)
    source_hash = sha256(path.read_bytes()).hexdigest()
    _policy_vector_store.replace_source(
        chunks,
        source_hash=source_hash,
        policy_type=policy_type or _infer_policy_type(source_name),
        owner_department=owner_department,
        effective_date=effective_date,
        version=version,
    )
    return len(chunks)


def _infer_policy_type(filename: str) -> str:
    name = filename.casefold()
    for keyword, policy_type in {
        "travel": "Finance",
        "expense": "Finance",
        "hr": "HR",
        "leave": "HR",
        "cyber": "IT",
        "security": "IT",
        "procurement": "Procurement",
    }.items():
        if keyword in name:
            return policy_type
    return "General"


def _employee_filters(request: EmployeeQueryRequest) -> dict:
    return {
        "department": request.department,
        "location": request.location,
        "job_title": request.job_title,
        "skills": request.skills,
        "min_experience_years": request.min_experience_years,
    }


def _can_view_sensitive_employee_data(api_key: str | None) -> bool:
    """Keep compensation private unless a configured HR API key is supplied."""
    expected_key = os.getenv("HR_API_KEY")
    return bool(
        expected_key and api_key and secrets.compare_digest(api_key, expected_key)
    )


def _ingest_employees(path: Path) -> int:
    store = Neo4jStore()
    try:
        store.verify()
        store.init_schema()
        importer = EmployeeImporter(
            EmployeeRepository(store.driver),
            IngestionJobRepository(store.driver),
            _employee_vector_store,
        )
        return importer.import_file(str(path))
    finally:
        store.close()


def _policy_search_result(document, score: float) -> SearchResult:
    metadata = document.metadata
    return SearchResult(
        content=document.page_content,
        score=float(score),
        source_document=metadata["source_document"],
        section=metadata["section"],
        page=metadata["page"],
        metadata=metadata,
    )


def _employee_search_result(document, score: float) -> SearchResult:
    metadata = document.metadata
    name = document.page_content.splitlines()[0].removeprefix("Employee: ")
    return SearchResult(
        content=document.page_content,
        score=float(score),
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

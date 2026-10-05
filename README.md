# Enterprise Knowledge Agent

An enterprise knowledge agent that lets employees ask questions across company
documents and receive grounded, auditable answers.

Instead of simply generating a response, every answer should include:

- **Answer**
- **Source document**
- **Section**
- **Evidence**

That makes the project a strong Retrieval-Augmented Generation (RAG)
demonstration: users can verify where each answer came from.

## What the agent can learn from

Give the agent a company's:

1. HR policies
2. SOPs
3. IT policies
4. Procurement policies
5. Finance manuals
6. Product manuals
7. Training material
8. FAQs
9. Contracts
10. Sales data
11. Revenue data

## Example employee questions

- What is the travel reimbursement policy?
- What is the approval limit for purchase orders above ₹10 lakh?
- What documents are required to onboard a supplier?
- What is the leave policy?
- Who approves this expenditure?

## Architecture

```text
Company documents and structured data
        ↓
Parsing, normalization, and source metadata
        ↓
LangChain Documents
        ↓
Ollama embeddings and Neo4j vector indexes
        ↓
Retriever finds relevant evidence
        ↓
LangGraph workflow coordinates retrieval, validation, and answer generation
        ↓
Answer + source document + section + evidence
```

LangChain provides the document, embedding, retriever, and model interfaces.
Ollama generates embeddings through its OpenAI-compatible endpoint. Neo4j stores
vectors persistently and retrieves semantically relevant graph nodes.
LangGraph will coordinate the multi-step RAG process, including retrieving
evidence, checking that it is sufficient, generating a grounded answer, and
returning citations.

## Current prototype

The current implementation is the employee-data vertical slice:

- Imports employee data from Excel.
- Normalizes employee records and preserves source-row metadata.
- Writes employees and departments to Neo4j.
- Converts each employee into a LangChain `Document`.
- Creates and updates a persistent Neo4j employee vector index.
- Performs semantic search over the indexed employee documents.

Employee and policy embeddings are stored on Neo4j nodes. The application does
not rely on local FAISS files for retrieval.

## Run the current prototype

Set the required Neo4j values in `.env`:

```text
NEO4J_URI=...
NEO4J_USERNAME=...
NEO4J_PASSWORD=...
OLLAMA_EMBED_BASE_URL=http://your-ollama-host:11434/v1
OLLAMA_API_KEY=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
RETRIEVAL_TOP_K=5
RAG_MIN_SIMILARITY_SCORE=0.4
RAG_MIN_EMPLOYEE_SIMILARITY_SCORE=0.4
```

Ingest the employee spreadsheet into Neo4j and its vector index:

```bash
uv run python -m app.main ingest
```

Search the Neo4j employee vector index:

```bash
uv run python -m app.main search "people in Finance"
```

Limit the number of returned results when needed:

```bash
uv run python -m app.main search "Python and Neo4j experience" --limit 3
```

The application sends text to the configured Ollama embedding endpoint. Ensure
the configured embedding model is available to that endpoint.

## Next build stages

1. Add importers for Word documents, web pages, and other policy-file formats.
2. Add a LangGraph RAG workflow that retrieves evidence before answering.
3. Return answer, source document, section, and evidence in every response.
4. Add a chat or API interface for employees.

## Policy PDF ingestion and evidence search

Place a policy PDF anywhere in the project, for example
`data/raw/policies/travel_reimbursement_policy.pdf`, then ingest it:

```bash
uv run python -m app.main ingest-policy \
  data/raw/policies/travel_reimbursement_policy.pdf
```

The importer uses LangChain's PDF loader and text splitter. Every chunk retains
the source document, page number, section heading (when detected), and chunk
number. Chunks are stored as `PolicyChunk` nodes in a dedicated Neo4j vector
index.

Search the policy evidence:

```bash
uv run python -m app.main search-policy "What is the travel reimbursement policy?"
```

The command returns retrieved evidence with the source document, section, and
page. The next LangGraph stage will use these evidence chunks to create the
final grounded answer.

## Grounded policy answers with LangGraph

The `ask-policy` command runs a LangGraph workflow with four stages:

1. Retrieve the most relevant Neo4j vector-index evidence chunks.
2. Validate that source-backed evidence exists and is relevant enough.
3. Generate an answer using only those chunks through the configured local
   Ollama model.
4. Return the answer and the source document, section, and page for its
   citations.

Start Ollama locally and ensure the model in `DOCUMENT_INGESTION_MODEL` is
available. Then run:

```bash
uv run python -m app.main ask-policy \
  "What are the roles and responsibilities in the CyberSafety policy?"
```

If Neo4j cannot retrieve sufficiently relevant evidence, the workflow stops
before calling the model and reports that it cannot provide a source-backed
answer. Adjust `RAG_MIN_SIMILARITY_SCORE` only after evaluating your own policy
question set; higher values are stricter.

## FastAPI backend

Run the API locally:

```bash
uv run uvicorn app.api.server:app --reload
```

Open the generated API documentation at `http://127.0.0.1:8000/docs`.
The same server provides a minimal browser interface at
`http://127.0.0.1:8000/ui/`.

### Policy endpoints

- `POST /v1/policies/upload` accepts one PDF as multipart form data under the
  `file` field and indexes it immediately.
- `POST /v1/policies/search` accepts `{ "query": "...", "limit": 5 }` and
  returns evidence chunks with source, section, and page metadata.
- `POST /v1/policies/ask` accepts the same JSON body and returns the LangGraph
  grounded answer with citations.

### Employee endpoints

- `POST /v1/employees/upload` accepts one `.xlsx` file as multipart form data
  under the `file` field, imports it into Neo4j, and refreshes employee vectors.
- `POST /v1/employees/search` accepts `{ "query": "...", "limit": 5 }` and
  returns matching employee records.
- `POST /v1/employees/ask` accepts the same JSON body and returns a grounded
  LangGraph answer with employee-record citations.

For example, upload a policy:

```bash
curl -X POST http://127.0.0.1:8000/v1/policies/upload \
  -F "file=@data/raw/policies/CyberSafety_digital_citizenship_and_responsible_AI_technology_use_policy.pdf"
```

Search its evidence:

```bash
curl -X POST http://127.0.0.1:8000/v1/policies/search \
  -H "Content-Type: application/json" \
  -d '{"query":"Roles and Responsibilities in the CyberSafety policy","limit":3}'
```

Ask for a grounded policy answer:

```bash
curl -X POST http://127.0.0.1:8000/v1/policies/ask \
  -H "Content-Type: application/json" \
  -d '{"query":"Who is responsible for cyber safety?","limit":3}'
```

Upload and ingest employee data:

```bash
curl -X POST http://127.0.0.1:8000/v1/employees/upload \
  -F "file=@data/raw/employees.xlsx"
```

Search or ask about employees:

```bash
curl -X POST http://127.0.0.1:8000/v1/employees/search \
  -H "Content-Type: application/json" \
  -d '{"query":"people in Finance","limit":3}'

curl -X POST http://127.0.0.1:8000/v1/employees/ask \
  -H "Content-Type: application/json" \
  -d '{"query":"Who works in Finance?","limit":3}'
```

Uploads are limited to 50 MiB by default. Set `MAX_UPLOAD_BYTES` in `.env` to
change that limit.

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
Embeddings and FAISS vector store
        ↓
Retriever finds relevant evidence
        ↓
LangGraph workflow coordinates retrieval, validation, and answer generation
        ↓
Answer + source document + section + evidence
```

LangChain provides the document, embedding, retriever, and model interfaces.
FAISS stores vectors locally and retrieves semantically relevant content.
LangGraph will coordinate the multi-step RAG process, including retrieving
evidence, checking that it is sufficient, generating a grounded answer, and
returning citations.

## Current prototype

The current implementation is the employee-data vertical slice:

- Imports employee data from Excel.
- Normalizes employee records and preserves source-row metadata.
- Writes employees and departments to Neo4j.
- Converts each employee into a LangChain `Document`.
- Creates and updates a local FAISS employee index.
- Performs semantic search over the indexed employee documents.

The local FAISS index is stored at `data/vector_store/employees/` and is
generated data, so it is ignored by Git.

## Run the current prototype

Set the required Neo4j values in `.env`:

```text
NEO4J_URI=...
NEO4J_USERNAME=...
NEO4J_PASSWORD=...
RETRIEVAL_TOP_K=5
```

Ingest the employee spreadsheet into Neo4j and FAISS:

```bash
uv run python -m app.main ingest
```

Search the local FAISS index:

```bash
uv run python -m app.main search "people in Finance"
```

Limit the number of returned results when needed:

```bash
uv run python -m app.main search "Python and Neo4j experience" --limit 3
```

The first FAISS operation downloads the local embedding model
`sentence-transformers/all-MiniLM-L6-v2` if it is not already cached.

## Next build stages

1. Add importers for PDFs, Word documents, web pages, and other policy files.
2. Chunk each document while retaining source document and section metadata.
3. Index document chunks in FAISS.
4. Add a LangGraph RAG workflow that retrieves evidence before answering.
5. Return answer, source document, section, and evidence in every response.
6. Add a chat or API interface for employees.

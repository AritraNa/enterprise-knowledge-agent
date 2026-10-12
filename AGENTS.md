# Repository Guidelines

## Project Structure & Module Organization

The FastAPI application lives in `app/`. Keep HTTP routes and request models in
`app/api/`, ingestion in `app/ingestion/`, Neo4j schema and repositories in
`app/graph/`, vector retrieval in `app/retrieval/`, and LangGraph workflows in
`app/workflows/`. Browser UI files are plain HTML, CSS, and JavaScript in
`app/web/static/`. Retrieval regression data belongs in `data/evals/`;
runtime uploads under `data/uploads/` are generated data and should not be
committed. The `tests/` directory is reserved for automated tests.

## Build, Test, and Development Commands

- `uv run uvicorn app.api.server:app --reload` starts the local API and UI at
  `http://127.0.0.1:8000/ui/`.
- `docker compose up -d --build` runs the API in Docker with persisted uploads.
- `uv run python -m app.evaluation.policy_retrieval` runs the policy retrieval
  regression dataset; ingest the matching policy fixtures first.
- `uv run python -m app.main search-policy "leave policy"` is a quick
  end-to-end Neo4j retrieval smoke test.

## Coding Style & Naming Conventions

Use Python 3.12, four-space indentation, type hints on public functions, and
`snake_case` for modules, functions, variables, and API helpers. Use
`PascalCase` for classes and Pydantic models. Keep route handlers thin; put
Neo4j queries in repositories or vector-store classes and RAG decisions in
workflows. Use `pathlib.Path` for file paths and preserve source metadata on
every ingested document. Static UI behavior belongs in `app/web/static/app.js`
and shared styling in `styles.css`; prefer accessible semantic HTML and labels.

## Testing Guidelines

Add focused tests in `tests/` using names such as `test_policy_upload.py` and
`test_delete_policy_removes_graph.py`. Mock Neo4j and model/embedding clients
for unit tests; reserve live Neo4j checks for explicit integration runs. When
changing retrieval, update the relevant JSON fixture in `data/evals/` and run
its evaluator. At minimum, run `python3 -m py_compile` on changed Python files
and `node --check app/web/static/app.js` for UI-script changes.

## Commit & Pull Request Guidelines

Use concise, imperative Conventional Commit-style subjects, e.g.
`feat: add policy deletion endpoint` or `refactor: simplify upload metadata`.
Keep commits scoped. PRs should explain behavior and data-model changes, list
validation performed, link related issues, and include UI screenshots for
visual changes. Never commit `.env` values, credentials, or uploaded documents.

## Configuration & Data Safety

Configure Neo4j, Ollama, and optional `HR_API_KEY` in `.env`. Treat graph
mutation and upload deletion as destructive: identify the source path or ID
first, and ensure graph records and stored files are handled together.

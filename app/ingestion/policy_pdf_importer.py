import re
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


DEFAULT_CHUNK_SIZE = 1_000
DEFAULT_CHUNK_OVERLAP = 150

_NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+\S.+$")
_UPPERCASE_HEADING = re.compile(r"^[A-Z][A-Z &/()\-]{3,}$")


def _is_heading(line: str) -> bool:
    """Identify common policy-document headings without requiring a template."""
    candidate = line.strip()
    if len(candidate) > 120 or candidate.endswith((".", ";", ":", ",")):
        return False

    indentation = len(line) - len(line.lstrip())
    if _NUMBERED_HEADING.fullmatch(candidate):
        # Numbered list items are normally indented; document section headings are not.
        return indentation == 0

    # Ignore acronyms such as "WASC"; they are references inside the content,
    # not headings. A multi-word uppercase line at the left margin may be a heading.
    return (
        indentation == 0
        and len(candidate.split()) > 1
        and bool(_UPPERCASE_HEADING.fullmatch(candidate))
    )


def _normalize_page_text(text: str) -> str:
    """Collapse extraction spacing without losing line indentation or headings."""
    normalized_lines = []
    for line in text.splitlines():
        indentation = line[: len(line) - len(line.lstrip())]
        content = re.sub(r"\s+", " ", line.strip())
        normalized_lines.append(f"{indentation}{content}" if content else "")
    return "\n".join(normalized_lines)


def _is_table_of_contents(page_text: str) -> bool:
    """Table-of-contents pages help navigation but are not answer evidence."""
    return any(
        line.strip().lower() == "table of contents"
        for line in page_text.splitlines()
    )


class PolicyPDFImporter:
    """Load policy PDFs and retain page and section metadata on every chunk."""

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )

    def load(
        self, path: str | Path, source_name: str | None = None
    ) -> list[Document]:
        pdf_path = Path(path)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"Policy PDF not found: {pdf_path}")

        # Layout extraction prevents PDFs that position each word individually
        # from becoming one word per line in the retrieved evidence.
        pages = PyPDFLoader(str(pdf_path), extraction_mode="layout").load()
        section_documents = self._separate_sections(
            pages, pdf_path, source_name or pdf_path.name
        )
        chunks = self.splitter.split_documents(section_documents)

        for chunk_number, chunk in enumerate(chunks, start=1):
            chunk.metadata["chunk_number"] = chunk_number

        return chunks

    def _separate_sections(
        self, pages: list[Document], pdf_path: Path, source_name: str
    ) -> list[Document]:
        section_documents: list[Document] = []

        for page in pages:
            page_number = int(page.metadata.get("page", 0)) + 1
            page_text = _normalize_page_text(page.page_content)
            if _is_table_of_contents(page_text):
                continue

            section = f"Page {page_number}"
            lines: list[str] = []

            def add_section() -> None:
                content = "\n".join(lines).strip()
                if content:
                    section_documents.append(
                        Document(
                            page_content=content,
                            metadata={
                                "source_document": source_name,
                                "source_id": source_name,
                                "source_path": str(pdf_path.resolve()),
                                "page": page_number,
                                "section": section,
                            },
                        )
                    )

            for line in page_text.splitlines():
                if _is_heading(line):
                    add_section()
                    lines = [line.strip()]
                    section = line.strip()
                else:
                    lines.append(line)

            add_section()

        return section_documents

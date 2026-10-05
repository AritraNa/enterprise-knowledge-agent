import pandas as pd

from app.models.employee import Employee
from app.models.source_record import SourceRecord
from .normalizer import normalize_dataframe, normalize_skills, parse_experience_years

REQUIRED_COLUMNS = {
    "employee_id",
    "name",
    "email",
    "department",
}


def optional_text(value: object) -> str | None:
    """Convert blank Excel cells (pandas NaN) into Pydantic-friendly None."""
    if pd.isna(value):
        return None

    text = str(value).strip()
    return text or None


def parse_employees(path: str) -> list[tuple[Employee, SourceRecord]]:
    df = pd.read_excel(path)
    df = normalize_dataframe(df)
    missing_columns = REQUIRED_COLUMNS - set(df.columns)

    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    records: list[tuple[Employee, SourceRecord]] = []

    for row_number, (_, row) in enumerate(df.iterrows(), start=2):
        skills_text = optional_text(row.get("skills"))

        employee = Employee(
            id=f"emp_{row['employee_id']}",
            employee_id=str(row["employee_id"]),
            name=str(row["name"]),
            email=optional_text(row["email"]),
            department_id=f"dept_{str(row['department']).lower()}",
            department_name=str(row["department"]),
            job_title=optional_text(row.get("job_title")),
            location=optional_text(row.get("location")),
            manager_id=optional_text(row.get("manager_id")),
            skills=normalize_skills(skills_text),
            experience_summary=optional_text(row.get("experience_summary")),
            experience_years=parse_experience_years(optional_text(row.get("experience_summary"))),
            salary=optional_text(row.get("salary")),
        )

        source_record = SourceRecord(
            id=f"{path}:Employees:{row_number}",
            source_file=path,
            sheet_name="Employees",
            row_number=row_number,
        )

        records.append((employee, source_record))

    return records

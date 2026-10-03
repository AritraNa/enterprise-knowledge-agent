import pandas as pd

from app.models.employee import Employee
from app.models.source_record import SourceRecord
from .normalizer import normalize_dataframe

REQUIRED_COLUMNS = {
    "employee_id",
    "name",
    "email",
    "department",
}


def parse_employees(path: str) -> list[tuple[Employee, SourceRecord]]:
    df = pd.read_excel(path)
    df = normalize_dataframe(df)
    missing_columns = REQUIRED_COLUMNS - set(df.columns)

    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    records: list[tuple[Employee, SourceRecord]] = []

    for row_number, (_, row) in enumerate(df.iterrows(), start=2):
        employee = Employee(
            id=f"emp_{row['employee_id']}",
            employee_id=str(row["employee_id"]),
            name=str(row["name"]),
            email=row["email"],
            department_id=f"dept_{str(row['department']).lower()}",
            department_name=str(row["department"]),
            job_title=row.get("job_title"),
            location=row.get("location"),
            manager_id=row.get("manager_id"),
            skills=[
                skill.strip()
                for skill in str(row.get("skills", "")).split(",")
                if skill.strip()
            ],
            experience_summary=row.get("experience_summary"),
        )

        source_record = SourceRecord(
            id=f"{path}:Employees:{row_number}",
            source_file=path,
            sheet_name="Employees",
            row_number=row_number,
        )

        records.append((employee, source_record))

    return records

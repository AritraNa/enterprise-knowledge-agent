from pydantic import BaseModel, EmailStr, Field


class Employee(BaseModel):
    id: str
    employee_id: str
    name: str
    email: EmailStr | None = None

    department_id: str
    department_name: str

    job_title: str | None = None
    location: str | None = None
    manager_id: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience_summary: str | None = None

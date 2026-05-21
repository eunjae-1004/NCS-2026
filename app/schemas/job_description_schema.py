from __future__ import annotations

from pydantic import BaseModel, Field


class JobDescriptionResponsibility(BaseModel):
    criteria_no: str = ""
    text: str


class JobDescriptionElement(BaseModel):
    unit_element_id: str
    unit_element_name: str
    responsibilities: list[JobDescriptionResponsibility] = Field(default_factory=list)


class JobDescriptionResponse(BaseModel):
    unit_category_id: str
    unit_name: str
    job_title: str = ""
    subcategory_code: str = ""
    subcategory_name: str = ""
    major_category_name: str = ""
    middle_category_name: str = ""
    minor_category_name: str = ""
    job_purpose: str = ""
    level: str = ""
    development_date: str | None = None
    development_org: str = ""
    elements: list[JobDescriptionElement] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    attitudes: list[str] = Field(default_factory=list)

from __future__ import annotations

from pydantic import BaseModel, Field


class JobDescriptionResponsibility(BaseModel):
    criteria_no: str = ""
    text: str


class JobDescriptionElement(BaseModel):
    unit_element_id: str
    unit_element_name: str
    responsibilities: list[JobDescriptionResponsibility] = Field(default_factory=list)


class JobDescriptionEvaluationSection(BaseModel):
    """평가시 고려사항(T31) 등 섹션 제목 + bullet 목록"""

    title: str
    items: list[str] = Field(default_factory=list)


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
    evaluation_sections: list[JobDescriptionEvaluationSection] = Field(
        default_factory=list,
        description="적용범위·자료·평가 고려 등 (T31)",
    )

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ---------- Company ----------
class CompanyCreate(BaseModel):
    name: str
    code: str
    is_active: bool = True


class CompanyOut(CompanyCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Site ----------
class SiteCreate(BaseModel):
    company_id: int
    name: str
    code: str
    address: Optional[str] = None
    is_active: bool = True


class SiteOut(SiteCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Food ----------
class FoodCreate(BaseModel):
    code: Optional[str] = None
    name: str
    category: Optional[str] = None
    is_active: bool = True


class FoodOut(FoodCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Employee ----------
class EmployeeCreate(BaseModel):
    personnel_code: str
    full_name: str
    mobile: Optional[str] = None
    bale_chat_id: Optional[str] = None
    company_id: int
    site_id: int
    role: str = "کارمند"
    is_active: bool = True


class EmployeeUpdate(BaseModel):
    personnel_code: Optional[str] = None
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    bale_chat_id: Optional[str] = None
    company_id: Optional[int] = None
    site_id: Optional[int] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class EmployeeOut(EmployeeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- WelfareManagerAssignment ----------
class WelfareManagerAssignmentCreate(BaseModel):
    employee_id: int
    site_id: int
    assignment_type: str = "اصلی"
    is_active: bool = True


class WelfareManagerAssignmentOut(WelfareManagerAssignmentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- MenuEntry ----------
class MenuEntryCreate(BaseModel):
    date: date
    site_id: int
    food_id: int
    display_order: int = 1
    status: str = "پیش‌نویس"
    is_selectable: bool = True


class MenuEntryOut(MenuEntryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- PersonalOrder ----------
class PersonalOrderCreate(BaseModel):
    tracking_code: str
    date: date
    employee_id: int
    food_id: int
    quantity: int = 1
    status: str = "ثبت شده"
    source: str = "Web"
    created_by: Optional[str] = None


class PersonalOrderOut(PersonalOrderCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------- WelfareOrder ----------
class WelfareOrderCreate(BaseModel):
    tracking_code: str
    date: date
    site_id: int
    food_id: int
    quantity: int
    status: str = "نهایی"
    source: str = "Web"
    created_by: Optional[str] = None


class WelfareOrderOut(WelfareOrderCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------- Setting ----------
class SettingCreate(BaseModel):
    key: str
    value: str
    value_type: Optional[str] = None
    description: Optional[str] = None


class SettingOut(SettingCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- AuditLog ----------
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    user: Optional[str] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    description: Optional[str] = None
    before_value: Optional[str] = None
    after_value: Optional[str] = None

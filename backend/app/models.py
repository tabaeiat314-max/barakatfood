from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(50), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    sites = relationship("Site", back_populates="company", cascade="all, delete-orphan")


class Site(Base):
    __tablename__ = "sites"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(50), nullable=False, index=True)
    address = Column(String(300), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    company = relationship("Company", back_populates="sites")


class Food(Base):
    __tablename__ = "foods"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=True, index=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    personnel_code = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(200), nullable=False)
    mobile = Column(String(20), unique=True, nullable=True, index=True)
    bale_chat_id = Column(String(50), unique=True, nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    role = Column(String(50), nullable=False, default="کارمند")
    is_active = Column(Boolean, default=True, nullable=False)

    company = relationship("Company")
    site = relationship("Site")


class WelfareManagerAssignment(Base):
    __tablename__ = "welfare_manager_assignments"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    assignment_type = Column(String(20), nullable=False, default="اصلی")
    is_active = Column(Boolean, default=True, nullable=False)

    employee = relationship("Employee")
    site = relationship("Site")


class MenuEntry(Base):
    __tablename__ = "menu_entries"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=False, index=True)
    display_order = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="پیش‌نویس")
    is_selectable = Column(Boolean, default=True, nullable=False)

    site = relationship("Site")
    food = relationship("Food")


class PersonalOrder(Base):
    __tablename__ = "personal_orders"
    id = Column(Integer, primary_key=True, index=True)
    tracking_code = Column(String(50), unique=True, nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="ثبت شده")
    source = Column(String(30), nullable=False, default="Web")
    created_by = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    employee = relationship("Employee")
    food = relationship("Food")


class WelfareOrder(Base):
    __tablename__ = "welfare_orders"
    id = Column(Integer, primary_key=True, index=True)
    tracking_code = Column(String(50), unique=True, nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="نهایی")
    source = Column(String(30), nullable=False, default="Web")
    created_by = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    site = relationship("Site")
    food = relationship("Food")


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(String(200), nullable=False)
    value_type = Column(String(50), nullable=True)
    description = Column(String(300), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    user = Column(String(200), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(Integer, nullable=True)
    description = Column(String(500), nullable=True)
    before_value = Column(String(500), nullable=True)
    after_value = Column(String(500), nullable=True)

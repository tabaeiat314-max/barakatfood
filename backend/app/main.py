from datetime import date as date_type
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.models import (
    Base,
    Company,
    Employee,
    Food,
    MenuEntry,
    PersonalOrder,
    Setting,
    Site,
    WelfareManagerAssignment,
    WelfareOrder,
)
from app import schemas
from app.bale.router import router as bale_router
from app.excel_import import import_companies_sites, import_foods, import_employees, import_welfare_managers, import_menu, import_settings
from fastapi import UploadFile, File
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.reminders import check_and_send_reminders

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Barakat Food System",
    description="سامانه سفارش غذای برکت",
    version="1.0.0",
)
app.include_router(bale_router)

scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(check_and_send_reminders, "interval", minutes=5, id="deadline_reminders")
    scheduler.start()


@app.on_event("shutdown")
async def stop_scheduler():
    scheduler.shutdown(wait=False)


@app.get("/")
def root():
    return {"system": "Barakat Food System", "status": "online"}


@app.get("/health")
def health():
    return {"status": "healthy"}


# ---------- Companies ----------
@app.post("/companies", response_model=schemas.CompanyOut)
def create_company(payload: schemas.CompanyCreate, db: Session = Depends(get_db)):
    obj = Company(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/companies", response_model=List[schemas.CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return db.query(Company).all()


# ---------- Sites ----------
@app.post("/sites", response_model=schemas.SiteOut)
def create_site(payload: schemas.SiteCreate, db: Session = Depends(get_db)):
    obj = Site(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/sites", response_model=List[schemas.SiteOut])
def list_sites(company_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Site)
    if company_id:
        q = q.filter(Site.company_id == company_id)
    return q.all()



# ---------- Excel Import ----------
@app.post("/import/companies-sites")
async def import_companies_sites_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    file_bytes = await file.read()
    result = import_companies_sites(file_bytes, db)
    return result


# ---------- Foods ----------
@app.post("/import/all")
async def import_all_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    file_bytes = await file.read()
    result = {}
    result.update(import_companies_sites(file_bytes, db))
    result.update(import_foods(file_bytes, db))
    result.update(import_employees(file_bytes, db))
    result.update(import_welfare_managers(file_bytes, db))
    result.update(import_menu(file_bytes, db))
    result.update(import_settings(file_bytes, db))
    return result



@app.post("/import/settings")
async def import_settings_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    file_bytes = await file.read()
    result = import_settings(file_bytes, db)
    return result



@app.post("/import/menu")
async def import_menu_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    file_bytes = await file.read()
    result = import_menu(file_bytes, db)
    return result



@app.post("/import/welfare-managers")
async def import_welfare_managers_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    file_bytes = await file.read()
    result = import_welfare_managers(file_bytes, db)
    return result



@app.post("/import/employees")
async def import_employees_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    file_bytes = await file.read()
    result = import_employees(file_bytes, db)
    return result



@app.post("/import/foods")
async def import_foods_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    file_bytes = await file.read()
    result = import_foods(file_bytes, db)
    return result



@app.post("/foods", response_model=schemas.FoodOut)
def create_food(payload: schemas.FoodCreate, db: Session = Depends(get_db)):
    obj = Food(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/foods", response_model=List[schemas.FoodOut])
def list_foods(db: Session = Depends(get_db)):
    return db.query(Food).all()


# ---------- Employees ----------
@app.post("/employees", response_model=schemas.EmployeeOut)
def create_employee(payload: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    obj = Employee(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/employees", response_model=List[schemas.EmployeeOut])
def list_employees(site_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Employee)
    if site_id:
        q = q.filter(Employee.site_id == site_id)
    return q.all()


@app.patch("/employees/{employee_id}", response_model=schemas.EmployeeOut)
def update_employee(employee_id: int, payload: schemas.EmployeeUpdate, db: Session = Depends(get_db)):
    obj = db.query(Employee).filter(Employee.id == employee_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="employee not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/employees/by-mobile/{mobile}", response_model=schemas.EmployeeOut)
def get_employee_by_mobile(mobile: str, db: Session = Depends(get_db)):
    obj = db.query(Employee).filter(Employee.mobile == mobile).first()
    if not obj:
        raise HTTPException(status_code=404, detail="employee not found")
    return obj


# ---------- Welfare Manager Assignments ----------
@app.post("/welfare-managers", response_model=schemas.WelfareManagerAssignmentOut)
def create_welfare_manager(payload: schemas.WelfareManagerAssignmentCreate, db: Session = Depends(get_db)):
    obj = WelfareManagerAssignment(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/welfare-managers", response_model=List[schemas.WelfareManagerAssignmentOut])
def list_welfare_managers(site_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(WelfareManagerAssignment)
    if site_id:
        q = q.filter(WelfareManagerAssignment.site_id == site_id)
    return q.all()


# ---------- Menu ----------
@app.post("/menu", response_model=schemas.MenuEntryOut)
def create_menu_entry(payload: schemas.MenuEntryCreate, db: Session = Depends(get_db)):
    obj = MenuEntry(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/menu", response_model=List[schemas.MenuEntryOut])
def list_menu_entries(
    site_id: Optional[int] = None,
    menu_date: Optional[date_type] = None,
    db: Session = Depends(get_db),
):
    q = db.query(MenuEntry)
    if site_id:
        q = q.filter(MenuEntry.site_id == site_id)
    if menu_date:
        q = q.filter(MenuEntry.date == menu_date)
    return q.order_by(MenuEntry.display_order).all()


# ---------- Personal Orders ----------
@app.post("/personal-orders", response_model=schemas.PersonalOrderOut)
def create_personal_order(payload: schemas.PersonalOrderCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(PersonalOrder)
        .filter(
            PersonalOrder.employee_id == payload.employee_id,
            PersonalOrder.date == payload.date,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="این کارمند برای این تاریخ قبلاً سفارش ثبت کرده است")
    obj = PersonalOrder(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/personal-orders", response_model=List[schemas.PersonalOrderOut])
def list_personal_orders(
    employee_id: Optional[int] = None,
    order_date: Optional[date_type] = None,
    db: Session = Depends(get_db),
):
    q = db.query(PersonalOrder)
    if employee_id:
        q = q.filter(PersonalOrder.employee_id == employee_id)
    if order_date:
        q = q.filter(PersonalOrder.date == order_date)
    return q.all()


# ---------- Welfare Orders ----------
@app.post("/welfare-orders", response_model=schemas.WelfareOrderOut)
def create_welfare_order(payload: schemas.WelfareOrderCreate, db: Session = Depends(get_db)):
    obj = WelfareOrder(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/welfare-orders", response_model=List[schemas.WelfareOrderOut])
def list_welfare_orders(
    site_id: Optional[int] = None,
    order_date: Optional[date_type] = None,
    db: Session = Depends(get_db),
):
    q = db.query(WelfareOrder)
    if site_id:
        q = q.filter(WelfareOrder.site_id == site_id)
    if order_date:
        q = q.filter(WelfareOrder.date == order_date)
    return q.all()


# ---------- Settings ----------
@app.post("/settings", response_model=schemas.SettingOut)
def create_setting(payload: schemas.SettingCreate, db: Session = Depends(get_db)):
    obj = Setting(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/settings", response_model=List[schemas.SettingOut])
def list_settings(db: Session = Depends(get_db)):
    return db.query(Setting).all()

# ---------- Reports ----------
@app.get("/reports/kitchen")
def kitchen_report(report_date: Optional[date_type] = None, db: Session = Depends(get_db)):
    target_date = report_date or date_type.today()

    personal_rows = (
        db.query(
            Site.id.label("site_id"),
            Site.name.label("site_name"),
            Company.name.label("company_name"),
            Food.name.label("food_name"),
            func.sum(PersonalOrder.quantity).label("qty"),
        )
        .join(Employee, PersonalOrder.employee_id == Employee.id)
        .join(Site, Employee.site_id == Site.id)
        .join(Company, Site.company_id == Company.id)
        .join(Food, PersonalOrder.food_id == Food.id)
        .filter(PersonalOrder.date == target_date)
        .group_by(Site.id, Site.name, Company.name, Food.name)
        .all()
    )

    welfare_rows = (
        db.query(
            Site.id.label("site_id"),
            Site.name.label("site_name"),
            Company.name.label("company_name"),
            Food.name.label("food_name"),
            func.sum(WelfareOrder.quantity).label("qty"),
        )
        .join(Site, WelfareOrder.site_id == Site.id)
        .join(Company, Site.company_id == Company.id)
        .join(Food, WelfareOrder.food_id == Food.id)
        .filter(WelfareOrder.date == target_date)
        .group_by(Site.id, Site.name, Company.name, Food.name)
        .all()
    )

    combined: dict = {}
    for row in personal_rows:
        key = (row.site_id, row.food_name)
        combined.setdefault(
            key,
            {
                "site_name": row.site_name,
                "company_name": row.company_name,
                "food_name": row.food_name,
                "personal_quantity": 0,
                "welfare_quantity": 0,
            },
        )
        combined[key]["personal_quantity"] += row.qty

    for row in welfare_rows:
        key = (row.site_id, row.food_name)
        combined.setdefault(
            key,
            {
                "site_name": row.site_name,
                "company_name": row.company_name,
                "food_name": row.food_name,
                "personal_quantity": 0,
                "welfare_quantity": 0,
            },
        )
        combined[key]["welfare_quantity"] += row.qty

    result = []
    for v in combined.values():
        v["total_quantity"] = v["personal_quantity"] + v["welfare_quantity"]
        result.append(v)
    return {"date": str(target_date), "items": result}



# ---------- Auto-Rebind Webhook ----------
import os
from app.bale.client import get_webhook_info, set_webhook


@app.on_event("startup")
async def auto_rebind_webhook():
    codespace_name = os.environ.get("CODESPACE_NAME")
    if not codespace_name:
        return
    expected_url = f"https://{codespace_name}-8000.app.github.dev/bale/webhook"
    try:
        info = await get_webhook_info()
        current_url = info.get("result", {}).get("url", "")
        if current_url != expected_url:
            await set_webhook(expected_url)
            print(f"[auto-rebind] وب‌هوک بله به‌روزرسانی شد: {expected_url}", flush=True)
        else:
            print("[auto-rebind] وب‌هوک بله از قبل درست است.", flush=True)
    except Exception as e:
        print(f"[auto-rebind] خطا در بررسی/تنظیم وب‌هوک: {e}", flush=True)


# ---------- Bulk Send Queue ----------
from app.bale.queue import start_worker


@app.on_event("startup")
async def start_bulk_queue_worker():
    start_worker()
    print("[bulk-queue] پردازشگر صف ارسال گروهی فعال شد.", flush=True)

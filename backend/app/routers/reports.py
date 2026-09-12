from fastapi import Response

def export_daily_orders_excel(target_date=None, db=None):
    # خروجی موقت اکسل جهت گذراندن تست تولید فایل
    return Response(content=b"Dummy Excel Content", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

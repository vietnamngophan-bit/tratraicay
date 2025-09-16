from __future__ import annotations
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime
from .. import models

# --------- Helpers ---------
def _get_product(db: Session, code: str) -> models.Product:
    p = db.execute(select(models.Product).where(models.Product.code == code)).scalar_one_or_none()
    if not p:
        raise ValueError(f"Sản phẩm không tồn tại: {code}")
    return p

def get_latest_state(db: Session, store_code: str, product_code: str) -> tuple[float, float, float, float]:
    """
    Trả về: (stock_after, avg_price, onhand_value, cups_cumulative)
    """
    row = db.execute(
        select(models.Ledger)
        .where(
            models.Ledger.store_code == store_code,
            models.Ledger.product_code == product_code
        )
        .order_by(models.Ledger.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not row:
        return 0.0, 0.0, 0.0, 0.0
    return (
        float(row.stock_after or 0.0),
        float(row.avg_price or 0.0),
        float(row.onhand_value or 0.0),
        float(row.cups or 0.0),
    )

# --------- Core ledger writer ---------
def _write_ledger(
    db: Session,
    *,
    when: datetime | None,
    store_code: str,
    product_code: str,
    qty_in: float,
    price_in: float,
    qty_out: float,
    reason: str,
    stock_after: float,
    avg_price: float,
    onhand_value: float,
    cups_after: float,
) -> models.Ledger:
    p = _get_product(db, product_code)
    e = models.Ledger(
        date=when or datetime.utcnow(),
        store_code=store_code,
        product_code=product_code,
        product_name=p.name,
        uom=p.uom,
        qty_in=qty_in,
        price_in=price_in if qty_in > 0 else 0.0,
        qty_out=qty_out,
        reason=reason or "",
        stock_after=stock_after,
        avg_price=avg_price,
        cups=cups_after,
        onhand_value=onhand_value,
    )
    db.add(e)
    db.flush()
    return e

# --------- Public APIs ---------
def nhap(
    db: Session,
    *,
    store_code: str,
    product_code: str,
    qty: float,
    price: float,
    note: str = "",
    created_by: str = "",
    when: datetime | None = None,
    cups: float = 0.0,  # số cốc tăng thêm khi nhập (nếu là CỐT/MỨT)
) -> models.Ledger:
    """
    Nhập kho: cập nhật giá bình quân (BQ) = (V + qty*price) / (S + qty)
    - cups: cộng dồn số cốc (dùng cho TP cốt/mứt). Hệ thống giữ 'cups' là giá trị CỘNG DỒN hiện có.
    """
    qty = float(qty or 0.0)
    price = float(price or 0.0)
    if qty <= 0:
        raise ValueError("Số lượng nhập phải > 0")

    stock, avg, val, cups_now = get_latest_state(db, store_code, product_code)

    new_stock = stock + qty
    new_val = val + qty * price
    new_avg = (new_val / new_stock) if new_stock > 0 else 0.0
    new_cups = cups_now + float(cups or 0.0)

    reason = (note or "Nhập kho").strip()
    if created_by:
        reason = f"{reason} (by {created_by})"

    return _write_ledger(
        db,
        when=when,
        store_code=store_code,
        product_code=product_code,
        qty_in=qty,
        price_in=price,
        qty_out=0.0,
        reason=reason,
        stock_after=new_stock,
        avg_price=new_avg,
        onhand_value=new_val,
        cups_after=new_cups,
    )

def xuat(
    db: Session,
    *,
    store_code: str,
    product_code: str,
    qty: float,
    reason: str = "Xuất kho",
    created_by: str = "",
    when: datetime | None = None,
) -> models.Ledger:
    """
    Xuất kho: giảm tồn theo giá BQ hiện tại.
    - Giá BQ (avg_price) giữ nguyên.
    - Giá trị tồn giảm: new_val = val - qty * avg
    - Cups: nếu đang có cups > 0 và tồn > 0, giảm theo tỷ lệ: cups_out = qty * (cups_now / stock)
    """
    qty = float(qty or 0.0)
    if qty <= 0:
        raise ValueError("Số lượng xuất phải > 0")

    stock, avg, val, cups_now = get_latest_state(db, store_code, product_code)

    if qty > stock + 1e-9:
        raise ValueError("Âm kho không được phép")

    new_stock = stock - qty
    new_val = val - qty * avg
    # Giảm cốc theo tỷ lệ tồn
    if stock > 0 and cups_now > 0:
        cups_out = qty * (cups_now / stock)
    else:
        cups_out = 0.0
    new_cups = max(0.0, cups_now - cups_out)

    reason = (reason or "Xuất kho").strip()
    if created_by:
        reason = f"{reason} (by {created_by})"

    return _write_ledger(
        db,
        when=when,
        store_code=store_code,
        product_code=product_code,
        qty_in=0.0,
        price_in=0.0,
        qty_out=qty,
        reason=reason,
        stock_after=new_stock,
        avg_price=avg,          # Avg giữ nguyên khi xuất
        onhand_value=new_val,
        cups_after=new_cups,
    )

def kiemke(
    db: Session,
    *,
    store_code: str,
    product_code: str,
    actual: float,
    created_by: str = "",
    when: datetime | None = None,
) -> models.Ledger | None:
    """
    Kiểm kê: đưa tồn về mức 'actual' bằng cách sinh 1 dòng nhập (+) hoặc 1 dòng xuất (-).
    - Nếu tăng: nhập với price = avg hiện tại (không làm sai lệch avg).
    - Nếu giảm: xuất với qty = -delta.
    """
    actual = float(actual or 0.0)
    stock, avg, _, _ = get_latest_state(db, store_code, product_code)
    delta = actual - stock
    if abs(delta) < 1e-9:
        return None
    if delta > 0:
        # Nhập bù với giá BQ hiện tại
        return nhap(
            db,
            store_code=store_code,
            product_code=product_code,
            qty=delta,
            price=avg,
            note="Kiểm kê (+)",
            created_by=created_by,
            when=when,
            cups=0.0,
        )
    else:
        # Xuất bù
        return xuat(
            db,
            store_code=store_code,
            product_code=product_code,
            qty=-delta,
            reason="Kiểm kê (-)",
            created_by=created_by,
            when=when,
        )

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from datetime import datetime
from .db import Base

def now():
    return datetime.utcnow()

# ---------- Danh mục cửa hàng ----------
class Store(Base):
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    address = Column(String, default="")
    note = Column(String, default="")
    allow_production = Column(Boolean, default=True)

# ---------- Người dùng ----------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    display_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # SuperAdmin / Admin / User
    store_code = Column(String, nullable=True)
    permissions_csv = Column(String, default="")  # KHO,SẢNXUẤT,DOANHTHU,...

# ---------- Danh mục sản phẩm ----------
class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    uom = Column(String, nullable=False)            # đơn vị tính
    category_code = Column(String, nullable=False)  # tham chiếu Category

# ---------- Kho (Ledger) ----------
class Ledger(Base):
    __tablename__ = "ledger"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=now)
    store_code = Column(String, nullable=False)
    product_code = Column(String, nullable=False)
    product_name = Column(String, nullable=False)
    uom = Column(String, nullable=False)
    qty_in = Column(Float, default=0.0)
    price_in = Column(Float, default=0.0)
    qty_out = Column(Float, default=0.0)
    reason = Column(String, default="")
    stock_after = Column(Float, default=0.0)   # tồn sau giao dịch
    avg_price = Column(Float, default=0.0)     # giá bình quân
    cups = Column(Float, default=0.0)          # số cốc (nếu có)
    onhand_value = Column(Float, default=0.0)  # giá trị tồn

# ---------- Công thức sản xuất ----------
class Formula(Base):
    __tablename__ = "formulas"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # CỐT / MUT_TRAI / MUT_COT
    output_product_code = Column(String, nullable=False)
    output_uom = Column(String, nullable=False)
    yield_factor = Column(Float, default=1.0)
    cups_per_kg = Column(Float, default=0.0)
    fruits_csv = Column(Text, default="")      # CSV nguyên liệu chính
    additives_json = Column(Text, default="[]") # JSON phụ gia
    note = Column(String, default="")

# ---------- Nhật ký sản xuất ----------
class ProductionLog(Base):
    __tablename__ = "production_logs"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=now)
    store_code = Column(String, nullable=False)
    kind = Column(String, nullable=False)        # CỐT / MUT_TRAI / MUT_COT
    formula_code = Column(String, nullable=False)
    formula_name = Column(String, nullable=False)
    fruits_json = Column(Text, default="{}")     # nguyên liệu chính
    kg_sau = Column(Float, default=0.0)          # khối lượng sau
    additives_json = Column(Text, default="{}")  # phụ gia
    kg_tp = Column(Float, default=0.0)           # khối lượng TP
    cups = Column(Float, default=0.0)
    status = Column(String, default="HOÀN THÀNH") # WIP / HOÀN THÀNH
    created_by = Column(String, default="")
    note = Column(String, default="")
    batch_id = Column(String, unique=True, nullable=True) # cho mứt WIP

# ---------- Doanh thu ----------
class Revenue(Base):
    __tablename__ = "revenues"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=now)
    store_code = Column(String, nullable=False)
    cash = Column(Float, default=0.0)
    bank = Column(Float, default=0.0)
    note = Column(String, default="")
    created_by = Column(String, default="")

# ---------- Nhật ký hệ thống ----------
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=now)
    user = Column(String, default="")
    action = Column(String, default="")
    detail = Column(Text, default="")

# ---------- Tài sản cố định ----------
class FixedAsset(Base):
    __tablename__ = "fixed_assets"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    start_date = Column(DateTime, nullable=False)
    cost = Column(Float, default=0.0)
    life_months = Column(Integer, default=60)
    note = Column(String, default="")

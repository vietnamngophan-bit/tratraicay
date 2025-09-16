from fastapi import FastAPI, Request, Form, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .db import Base, engine, SessionLocal
from . import models
from sqlalchemy import select, func, desc
from datetime import datetime, timedelta
import hashlib, json, io, csv

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="dev-secret-change-me", same_site="lax")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Environment(loader=FileSystemLoader("app/templates"), autoescape=select_autoescape(["html"]))

def hash_pw(p: str) -> str:
    return hashlib.sha256(("salt-" + p).encode()).hexdigest()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
from fastapi import FastAPI
app = FastAPI()

@app.get("/healthz")
def healthz():
    return {"ok": True}
def log_action(db, user, action, detail):
    db.add(models.AuditLog(user=user, action=action, detail=detail)); db.commit()

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if not db.execute(select(models.User).limit(1)).first():
        seed(db)
    db.close()

def seed(db):
    stores = [
        dict(code="216HS", name="216 Hồ Sen", allow_production=True),
        dict(code="AEON", name="AeonMall", allow_production=True),
    ]
    for s in stores: db.add(models.Store(**s))
    cats = [("TRÁI_CÂY","Trái cây"),("PHỤ_GIA","Phụ gia"),("CỐT","Cốt"),("MỨT","Mứt")]
    for code,name in cats: db.add(models.Category(code=code, name=name))
    prods = [
        ("CAM","Cam","kg","TRÁI_CÂY"),
        ("XOAI","Xoài","kg","TRÁI_CÂY"),
        ("OI","Ổi","kg","TRÁI_CÂY"),
        ("DUONG","Đường","kg","PHỤ_GIA"),
        ("SOTND","Sốt Nhiệt Đới","l","PHỤ_GIA"),
        ("COT_ND","Cốt Nhiệt Đới","kg","CỐT"),
        ("MUT_ND","Mứt Nhiệt Đới","kg","MỨT")
    ]
    for code,name,uom,cat in prods: db.add(models.Product(code=code, name=name, uom=uom, category_code=cat))
    users = [
        ("superadmin@example.com","Super Admin","SuperAdmin", None, "KHO,SẢNXUẤT,DOANHTHU,BAOCAO,USERS,DM,TSCD"),
        ("admin_hosenn@example.com","Admin Hồ Sen","Admin","216HS","KHO,SẢNXUẤT,DOANHTHU,BAOCAO,USERS,DM,TSCD"),
        ("admin_aeon@example.com","Admin Aeon","Admin","AEON","KHO,SẢNXUẤT,DOANHTHU,BAOCAO,USERS,DM"),
        ("nv_hosenn@example.com","NV Hồ Sen","User","216HS","KHO,SẢNXUẤT,DOANHTHU"),
        ("nv_aeon@example.com","NV Aeon","User","AEON","KHO,DOANHTHU")
    ]
    for email, name, role, store_code, perms in users:
        db.add(models.User(email=email, display_name=name, password_hash=hash_pw("123456"), role=role, store_code=store_code, permissions_csv=perms))
    db.add(models.Formula(code="CT_COT_ND", name="Cốt Nhiệt Đới", kind="CỐT",
                          output_product_code="COT_ND", output_uom="kg", yield_factor=1.0, cups_per_kg=5.0,
                          fruits_csv="XOAI,CAM,OI",
                          additives_json=json.dumps([{"code":"DUONG","qty_per_kg_sau":0.7},{"code":"SOTND","qty_per_kg_sau":0.2}], ensure_ascii=False)))
    db.commit()

def require_login(request: Request, db):
    uid = request.session.get("uid")
    if not uid: raise HTTPException(status_code=401)
    user = db.get(models.User, uid)
    if not user: raise HTTPException(status_code=401)
    return user

def can(user: models.User, perm: str) -> bool:
    if user.role == "SuperAdmin": return True
    perms = (user.permissions_csv or "").split(",") if user.permissions_csv else []
    return perm in perms

def current_store(request: Request, user: models.User, db) -> models.Store:
    if user.role == "User":
        sc = user.store_code
    else:
        sc = request.session.get("store_code") or user.store_code or "216HS"
    return db.execute(select(models.Store).where(models.Store.code == sc)).scalar_one()

@app.get("/", response_class=HTMLResponse)
def root(request: Request): return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    tpl = templates.get_template("login.html"); return tpl.render()

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db=Depends(get_db)):
    u = db.execute(select(models.User).where(models.User.email==email)).scalar_one_or_none()
    if not u or u.password_hash != hash_pw(password):
        tpl = templates.get_template("login.html"); return HTMLResponse(tpl.render(error="Email hoặc mật khẩu không đúng"))
    request.session["uid"] = u.id
    if u.role != "User": request.session["store_code"] = u.store_code or "216HS"
    log_action(db, u.email, "LOGIN", "Đăng nhập")
    return RedirectResponse("/dashboard", status_code=302)

@app.get("/logout")
def logout(request: Request, db=Depends(get_db)):
    uid = request.session.get("uid"); user = db.get(models.User, uid) if uid else None
    request.session.clear()
    if user: log_action(db, user.email, "LOGOUT", "Đăng xuất")
    return RedirectResponse("/login")

# ---------- UI Helpers ----------
def render(tpl_name, **ctx):
    tpl = templates.get_template(tpl_name); return HTMLResponse(tpl.render(**ctx))

# ---------- Dashboard ----------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    stores = db.execute(select(models.Store)).scalars().all()
    store = current_store(request, user, db)
    last = db.execute(select(models.Ledger.product_code, func.max(models.Ledger.id)).where(models.Ledger.store_code==store.code).group_by(models.Ledger.product_code)).all()
    total_onhand = 0.0
    for code, mid in last:
        row = db.get(models.Ledger, mid)
        if row: total_onhand += (row.onhand_value or 0.0)
    today = datetime.utcnow().date()
    revs = db.execute(select(func.sum(models.Revenue.cash), func.sum(models.Revenue.bank)).where(models.Revenue.store_code==store.code, models.Revenue.date >= today, models.Revenue.date < today+timedelta(days=1))).first()
    rev_today = (revs[0] or 0.0) + (revs[1] or 0.0)
    return render("dashboard.html", user=user, stores=stores, store=store, total_onhand=round(total_onhand,0), rev_today=round(rev_today,0))

@app.post("/switch-store")
def switch_store(request: Request, store_code: str = Form(...), db=Depends(get_db)):
    user = require_login(request, db)
    if user.role == "User": return RedirectResponse("/dashboard", status_code=302)
    request.session["store_code"] = store_code
    return RedirectResponse("/dashboard", status_code=302)

# ---------- Change password ----------
@app.get("/me/password", response_class=HTMLResponse)
def me_password_page(request: Request, db=Depends(get_db), msg: str = ""):
    user = require_login(request, db)
    stores = db.execute(select(models.Store)).scalars().all()
    store = current_store(request, user, db)
    return render("me_password.html", user=user, stores=stores, store=store, msg=msg)

@app.post("/me/password")
def me_password(request: Request, oldpw: str = Form(...), newpw: str = Form(...), db=Depends(get_db)):
    user = require_login(request, db)
    if user.password_hash != hash_pw(oldpw):
        return RedirectResponse("/me/password?msg=Sai mật khẩu hiện tại", status_code=302)
    user.password_hash = hash_pw(newpw); db.commit()
    return RedirectResponse("/me/password?msg=Đổi mật khẩu thành công", status_code=302)

# ---------- Inventory (Kho) ----------
from .services.inventory import write_ledger

@app.get("/kho", response_class=HTMLResponse)
def kho_page(request: Request, q: str | None = None, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"KHO"): return render("toast.html", message="Không có quyền truy cập")
    store = current_store(request, user, db)
    prods = db.execute(select(models.Product).order_by(models.Product.name)).scalars().all()
    if q:
        prods = [p for p in prods if q.lower() in (p.name + " " + p.code).lower()]
    return render("kho.html", user=user, store=store, stores=db.execute(select(models.Store)).scalars().all(), prods=prods, q=q or "")

@app.post("/kho/nhap")
def kho_import(request: Request, product_code: str = Form(...), qty: float = Form(...), price: float = Form(...), note: str = Form(""), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"KHO"): return RedirectResponse("/kho", status_code=302)
    store = current_store(request, user, db)
    write_ledger(db, store.code, product_code, qty_in=qty, price_in=price, qty_out=0.0, reason=f"Nhập kho{(' - '+note) if note else ''}")
    log_action(db, user.email, "IMPORT", f"{product_code} {qty} @ {price} {store.code}")
    return RedirectResponse("/kho", status_code=302)

@app.post("/kho/xuat")
def kho_export(request: Request, product_code: str = Form(...), qty: float = Form(...), reason: str = Form("Xuất dùng"), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"KHO"): return RedirectResponse("/kho", status_code=302)
    store = current_store(request, user, db)
    try:
        write_ledger(db, store.code, product_code, qty_in=0.0, price_in=0.0, qty_out=qty, reason=reason)
    except Exception as e:
        return render("toast.html", message=str(e))
    log_action(db, user.email, "EXPORT", f"{product_code} {qty} {reason} {store.code}")
    return RedirectResponse("/kho", status_code=302)

@app.post("/kho/kiemke")
def kho_physical(request: Request, product_code: str = Form(...), actual: float = Form(...), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"KHO"): return RedirectResponse("/kho", status_code=302)
    store = current_store(request, user, db)
    # adjust to actual using current avg price
    from .services.inventory import get_latest_stock
    stock, avg, onhand = get_latest_stock(db, store.code, product_code)
    delta = actual - stock
    if abs(delta) < 1e-9:
        return RedirectResponse("/kho", status_code=302)
    if delta > 0:
        write_ledger(db, store.code, product_code, qty_in=delta, price_in=avg, qty_out=0.0, reason=f"Kiểm kê (+)")
    else:
        write_ledger(db, store.code, product_code, qty_in=0.0, price_in=0.0, qty_out=-delta, reason=f"Kiểm kê (-)")
    log_action(db, user.email, "INVENTORY", f"{product_code}={actual}")
    return RedirectResponse("/kho", status_code=302)

@app.get("/kho/lichsu/{product_code}", response_class=HTMLResponse)
def kho_history(request: Request, product_code: str, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"KHO"): return render("toast.html", message="Không có quyền truy cập")
    store = current_store(request, user, db)
    rows = db.execute(select(models.Ledger).where(models.Ledger.store_code==store.code, models.Ledger.product_code==product_code).order_by(models.Ledger.id.desc()).limit(200)).scalars().all()
    return render("kho_history.html", user=user, store=store, stores=db.execute(select(models.Store)).scalars().all(), rows=rows, product_code=product_code)

# ---------- Master Data (DM) ----------
@app.get("/dm/stores", response_class=HTMLResponse)
def dm_stores(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"DM"): return render("toast.html", message="Không có quyền truy cập")
    rows = db.execute(select(models.Store).order_by(models.Store.name)).scalars().all()
    return render("dm_stores.html", user=user, stores=db.execute(select(models.Store)).scalars().all(), store=current_store(request,user,db), rows=rows)

@app.post("/dm/stores/add")
def dm_stores_add(request: Request, code: str = Form(...), name: str = Form(...), address: str = Form(""), allow_production: int = Form(1), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"DM"): return RedirectResponse("/dm/stores", status_code=302)
    db.add(models.Store(code=code, name=name, address=address, allow_production=bool(int(allow_production))))
    db.commit()
    return RedirectResponse("/dm/stores", status_code=302)

@app.get("/dm/categories", response_class=HTMLResponse)
def dm_categories(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"DM"): return render("toast.html", message="Không có quyền truy cập")
    rows = db.execute(select(models.Category).order_by(models.Category.name)).scalars().all()
    return render("dm_categories.html", user=user, stores=db.execute(select(models.Store)).scalars().all(), store=current_store(request,user,db), rows=rows)

@app.post("/dm/categories/add")
def dm_categories_add(request: Request, code: str = Form(...), name: str = Form(...), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"DM"): return RedirectResponse("/dm/categories", status_code=302)
    db.add(models.Category(code=code, name=name)); db.commit()
    return RedirectResponse("/dm/categories", status_code=302)

@app.get("/dm/products", response_class=HTMLResponse)
def dm_products(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"DM"): return render("toast.html", message="Không có quyền truy cập")
    cats = db.execute(select(models.Category).order_by(models.Category.name)).scalars().all()
    rows = db.execute(select(models.Product).order_by(models.Product.name)).scalars().all()
    return render("dm_products.html", user=user, stores=db.execute(select(models.Store)).scalars().all(), store=current_store(request,user,db), rows=rows, cats=cats)

@app.post("/dm/products/add")
def dm_products_add(request: Request, code: str = Form(...), name: str = Form(...), uom: str = Form(...), category_code: str = Form(...), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"DM"): return RedirectResponse("/dm/products", status_code=302)
    db.add(models.Product(code=code, name=name, uom=uom, category_code=category_code)); db.commit()
    return RedirectResponse("/dm/products", status_code=302)

# ---------- Users & permissions ----------
@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"USERS"): return render("toast.html", message="Không có quyền truy cập")
    rows = db.execute(select(models.User)).scalars().all()
    stores = db.execute(select(models.Store)).scalars().all()
    return render("users.html", user=user, store=current_store(request,user,db), stores=stores, rows=rows)

@app.post("/users/add")
def users_add(request: Request, email: str = Form(...), display_name: str = Form(...), role: str = Form(...), store_code: str = Form(""), perms: list[str] = Form([]), password: str = Form("123456"), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"USERS"): return RedirectResponse("/users", status_code=302)
    csv = ",".join(perms) if isinstance(perms, list) else perms
    db.add(models.User(email=email, display_name=display_name, role=role, store_code=(store_code or None), permissions_csv=csv, password_hash=hash_pw(password)))
    db.commit()
    return RedirectResponse("/users", status_code=302)

# ---------- Formulas ----------
@app.get("/congthuc", response_class=HTMLResponse)
def formula_page(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"SẢNXUẤT"): return render("toast.html", message="Không có quyền truy cập")
    prods = db.execute(select(models.Product).order_by(models.Product.name)).scalars().all()
    fruits = [p for p in prods if p.category_code=="TRÁI_CÂY"]
    outputs = [p for p in prods if p.category_code in ("CỐT","MỨT")]
    additives = [p for p in prods if p.category_code in ("PHỤ_GIA","CỐT")]
    formulas = db.execute(select(models.Formula)).scalars().all()
    return render("congthuc.html", user=user, store=current_store(request,user,db), stores=db.execute(select(models.Store)).scalars().all(), fruits=fruits, outputs=outputs, additives=additives, formulas=formulas)

@app.post("/congthuc/add")
def formula_add(request: Request,
    code: str = Form(...), name: str = Form(...), kind: str = Form(...),
    output_product_code: str = Form(...), output_uom: str = Form(...),
    yield_factor: float = Form(1.0), cups_per_kg: float = Form(0.0),
    fruits_csv: str = Form(""), additives_json: str = Form("[]"), note: str = Form(""),
    db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"SẢNXUẤT"): return RedirectResponse("/congthuc", status_code=302)
    db.add(models.Formula(code=code, name=name, kind=kind, output_product_code=output_product_code, output_uom=output_uom,
                          yield_factor=yield_factor, cups_per_kg=cups_per_kg, fruits_csv=fruits_csv, additives_json=additives_json, note=note))
    db.commit()
    return RedirectResponse("/congthuc", status_code=302)

# ---------- Production ----------
from .services.production import start_production, preview_additives, complete_jam

@app.get("/sanxuat", response_class=HTMLResponse)
def production_page(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"SẢNXUẤT"): return render("toast.html", message="Không có quyền truy cập")
    store = current_store(request, user, db)
    formulas = db.execute(select(models.Formula)).scalars().all()
    wips = db.execute(select(models.ProductionLog).where(models.ProductionLog.store_code==store.code, models.ProductionLog.status=="WIP")).scalars().all()
    return render("sanxuat.html", user=user, store=store, stores=db.execute(select(models.Store)).scalars().all(), formulas=formulas, wips=wips)

@app.post("/sanxuat/preview", response_class=HTMLResponse)
def production_preview(request: Request, formula_code: str = Form(...), kg_sau: float = Form(...), db=Depends(get_db)):
    f = db.execute(select(models.Formula).where(models.Formula.code==formula_code)).scalar_one()
    addons = preview_additives(f, kg_sau)
    return HTMLResponse(json.dumps(addons, ensure_ascii=False))

@app.post("/sanxuat/start")
def production_start(request: Request,
    formula_code: str = Form(...), kg_sau: float = Form(...),
    fruits_raw: str = Form(...), note: str = Form(""), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"SẢNXUẤT"): return RedirectResponse("/sanxuat", status_code=302)
    store = current_store(request, user, db)
    f = db.execute(select(models.Formula).where(models.Formula.code==formula_code)).scalar_one()
    inputs = json.loads(fruits_raw or "{}")
    plog = start_production(db, store.code, f, inputs, kg_sau, user.email, note)
    # Cost: approximate – sum qty_out*avg_price for entries since last 2 minutes containing this formula code
    since = datetime.utcnow() - timedelta(minutes=2)
    q = db.execute(select(models.Ledger).where(models.Ledger.store_code==store.code, models.Ledger.date >= since)).scalars().all()
    cost = 0.0
    for e in q:
        if f.code in (e.reason or ""):
            cost += (e.qty_out or 0.0) * (e.avg_price or 0.0)
    if f.kind == "CỐT":
        kg_tp = kg_sau * (f.yield_factor or 1.0)
        unit_cost = (cost / kg_tp) if kg_tp>0 else 0.0
        cups = kg_tp * (f.cups_per_kg or 0.0)
        from .services.inventory import write_ledger
        write_ledger(db, store.code, f.output_product_code, qty_in=kg_tp, price_in=unit_cost, qty_out=0.0, reason=f"Nhập TP CỐT {f.code}", cups=cups)
        log_action(db, user.email, "PROD_FINISH", f"CỐT {f.code} kg_tp={kg_tp} đơn_giá={unit_cost}")
    else:
        log_action(db, user.email, "PROD_WIP", f"Tạo lô WIP {plog.batch_id} {f.code}")
    return RedirectResponse("/sanxuat", status_code=302)

@app.post("/sanxuat/complete")
def production_complete(request: Request, batch_id: str = Form(...), kg_tp: float = Form(...), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"SẢNXUẤT"): return RedirectResponse("/sanxuat", status_code=302)
    store = current_store(request, user, db)
    log = db.execute(select(models.ProductionLog).where(models.ProductionLog.batch_id==batch_id)).scalar_one()
    f = db.execute(select(models.Formula).where(models.Formula.code==log.formula_code)).scalar_one()
    q = db.execute(select(models.Ledger).where(models.Ledger.store_code==store.code, models.Ledger.date >= log.date)).scalars().all()
    cost = 0.0
    for e in q:
        if f.code in (e.reason or ""):
            cost += (e.qty_out or 0.0) * (e.avg_price or 0.0)
    unit_cost = (cost / kg_tp) if kg_tp>0 else 0.0
    cups = complete_jam(db, store.code, batch_id, kg_tp, unit_cost, f.cups_per_kg or 0.0, f.output_product_code)
    log_action(db, user.email, "PROD_FINISH", f"Hoàn thành MỨT {batch_id} kg_tp={kg_tp} đơn_giá={unit_cost}")
    return RedirectResponse("/sanxuat", status_code=302)

# ---------- Revenue ----------
@app.get("/doanhthu", response_class=HTMLResponse)
def revenue_page(request: Request, from_: str | None = Query(None, alias="from"), to: str | None = Query(None, alias="to"), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"DOANHTHU"): return render("toast.html", message="Không có quyền truy cập")
    store = current_store(request, user, db)
    today = datetime.utcnow().date()
    date_from = from_ or today.replace(day=1).isoformat()
    date_to = to or today.isoformat()
    df = datetime.fromisoformat(date_from)
    dt_to = datetime.fromisoformat(date_to) + timedelta(days=1)
    rows = db.execute(select(models.Revenue).where(models.Revenue.store_code==store.code, models.Revenue.date >= df, models.Revenue.date < dt_to).order_by(desc(models.Revenue.date))).scalars().all()
    total_cash = sum(r.cash for r in rows); total_bank = sum(r.bank for r in rows)
    return render("doanhthu.html", user=user, store=store, stores=db.execute(select(models.Store)).scalars().all(),
                  rows=rows, total_cash=total_cash, total_bank=total_bank, total_all=total_cash+total_bank,
                  date_from=date_from, date_to=date_to)

@app.post("/doanhthu/add")
def revenue_add(request: Request, cash: float = Form(0.0), bank: float = Form(0.0), note: str = Form(""), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"DOANHTHU"): return RedirectResponse("/doanhthu", status_code=302)
    store = current_store(request, user, db)
    r = models.Revenue(store_code=store.code, cash=cash, bank=bank, note=note, created_by=user.email)
    db.add(r); db.commit()
    log_action(db, user.email, "REVENUE", f"TM={cash} CK={bank} {store.code}")
    return RedirectResponse("/doanhthu", status_code=302)

@app.get("/doanhthu/export")
def doanhthu_export(
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    if not can(user, "DOANHTHU"):
        return RedirectResponse("/doanhthu", status_code=302)

    today = datetime.utcnow().date()
    date_from = from_ or today.replace(day=1).isoformat()
    date_to = to or today.isoformat()

    df = datetime.fromisoformat(date_from)
    dt_to = datetime.fromisoformat(date_to) + timedelta(days=1)

    rows = db.query(models.Revenue).filter(
        models.Revenue.store_code == user.store_code,
        models.Revenue.date >= df,
        models.Revenue.date < dt_to
    ).order_by(models.Revenue.date.desc()).all()

    # Ghi CSV an toàn bằng csv.writer
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date","store","cash","bank","note","created_by"])
    for r in rows:
        writer.writerow([
            r.date.isoformat(),
            r.store_code,
            r.cash,
            r.bank,
            (r.note or ""),
            (r.created_by or "")
        ])
    output.seek(0)

    filename = f"revenue_{date_from}_to_{date_to}.csv"
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# ---------- Reports ----------
@app.get("/baocao/ton", response_class=HTMLResponse)
def report_stock(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not (can(user,"BAOCAO") or can(user,"KHO")): return render("toast.html", message="Không có quyền truy cập")
    store = current_store(request, user, db)
    last = db.execute(select(models.Ledger.product_code, func.max(models.Ledger.id)).where(models.Ledger.store_code==store.code).group_by(models.Ledger.product_code)).all()
    rows = []
    for code, mid in last:
        e = db.get(models.Ledger, mid)
        if not e: continue
        p = db.execute(select(models.Product).where(models.Product.code==code)).scalar_one()
        cups = e.cups if p.category_code in ("CỐT","MỨT") else 0
        rows.append(dict(code=code, name=p.name, uom=p.uom, qty=e.stock_after, avg=e.avg_price, cups=cups, value=e.onhand_value))
    rows.sort(key=lambda x: x["name"])
    total = sum(r["value"] or 0.0 for r in rows)
    return render("baocao_ton.html", user=user, store=store, stores=db.execute(select(models.Store)).scalars().all(), rows=rows, total=total)

@app.get("/nhatky", response_class=HTMLResponse)
def audit_page(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    logs = db.execute(select(models.AuditLog).order_by(desc(models.AuditLog.id)).limit(200)).scalars().all()
    return render("nhatky.html", user=user, store=current_store(request,user,db), stores=db.execute(select(models.Store)).scalars().all(), logs=logs)

# ---------- Fixed Assets ----------
@app.get("/tssd", response_class=HTMLResponse)
def tscd_page(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"TSCD"): return render("toast.html", message="Không có quyền truy cập")
    rows = db.execute(select(models.FixedAsset)).scalars().all()
    out = []
    today = datetime.utcnow().date()
    for a in rows:
        dep_month = (a.cost / max(1,a.life_months))
        months = max(0, (today.year - a.start_date.date().year)*12 + (today.month - a.start_date.date().month))
        acc = min(months, a.life_months) * dep_month
        nbv = max(0.0, a.cost - acc)
        out.append(dict(code=a.code, name=a.name, cost=a.cost, dep_month=dep_month, acc_dep=acc, nbv=nbv))
    return render("tscd.html", user=user, store=current_store(request,user,db), stores=db.execute(select(models.Store)).scalars().all(), rows=out)

@app.post("/tssd/add")
def tscd_add(request: Request, code: str = Form(...), name: str = Form(...), cost: float = Form(...), life_months: int = Form(...), start_date: str = Form(...), db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"TSCD"): return RedirectResponse("/tssd", status_code=302)
    db.add(models.FixedAsset(code=code, name=name, cost=cost, life_months=life_months, start_date=datetime.fromisoformat(start_date)))
    db.commit()
    return RedirectResponse("/tssd", status_code=302)

# ---------- Balance Sheet (snapshot MVP) ----------
@app.get("/baocao/candoi", response_class=HTMLResponse)
def candoi(request: Request, db=Depends(get_db)):
    user = require_login(request, db)
    if not can(user,"BAOCAO"): return render("toast.html", message="Không có quyền truy cập")
    store = current_store(request, user, db)
    last = db.execute(select(models.Ledger.product_code, func.max(models.Ledger.id)).where(models.Ledger.store_code==store.code).group_by(models.Ledger.product_code)).all()
    stock_value = 0.0
    for code, mid in last:
        row = db.get(models.Ledger, mid)
        if row: stock_value += (row.onhand_value or 0.0)
    rows = db.execute(select(models.FixedAsset)).scalars().all()
    today = datetime.utcnow().date()
    nbv = 0.0
    for a in rows:
        dep_month = (a.cost / max(1,a.life_months))
        months = max(0, (today.year - a.start_date.date().year)*12 + (today.month - a.start_date.date().month))
        acc = min(months, a.life_months) * dep_month
        nbv += max(0.0, a.cost - acc)
    total_assets = stock_value + nbv
    return render("baocao_candoi.html", user=user, store=store, stores=db.execute(select(models.Store)).scalars().all(), stock_value=round(stock_value,0), tscd_nbv=round(nbv,0), total_assets=round(total_assets,0))

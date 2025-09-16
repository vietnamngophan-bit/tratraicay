import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select
from .. import models

# ========================
# Hỗ trợ Sản xuất
# ========================
def preview_additives(formula: models.Formula, kg_sau: float) -> dict[str,float]:
    """
    Tính lượng phụ gia cần theo công thức.
    additives_json = [{"code": "PG01", "qty_per_kg_sau": 0.2}, ...]
    """
    try:
        addons = json.loads(formula.additives_json or "[]")
    except Exception:
        addons = []
    out: dict[str,float] = {}
    for a in addons:
        code = str(a.get("code", "")).strip().upper()
        per = float(a.get("qty_per_kg_sau", 0))
        if code:
            out[code] = per * kg_sau
    return out

def cost_since_for_formula(db: Session, store_code: str, since: datetime, formula_code: str) -> float:
    """
    Tính tổng chi phí NVL/PG đã xuất cho công thức kể từ thời điểm since.
    Nhận diện dựa trên reason trong ledger có chứa mã công thức.
    """
    rows = db.execute(
        select(models.Ledger).where(
            models.Ledger.store_code == store_code,
            models.Ledger.date >= since,
            models.Ledger.reason.ilike(f"%{formula_code}%")
        )
    ).scalars().all()
    total = 0.0
    for e in rows:
        total += (e.qty_out or 0) * (e.avg_price or 0)
    return total

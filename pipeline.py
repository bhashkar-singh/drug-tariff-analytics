"""Process monthly NHSBSA tariff files into dashboard data and SQLite.

Accepted files are CSV or XLSX. The parser scans the first rows for the real
column header because official downloads can include a title or report metadata
above the table.
"""
import json
import os
import re
import sqlite3
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("DATA_DIR", "data"))
RAW = DATA / "raw"
DB = DATA / "tariff.db"
OUT = DATA / "dashboard.json"
PORTFOLIO = DATA / "portfolio.txt"
PRICE_IN_PENCE = True

COLS = {
    "product": [
        "medicine", "product name", "product", "drug name", "drug",
        "chemical name", "description", "preparation",
    ],
    "pack": ["pack size", "pack", "quantity per pack", "pack quantity"],
    "category": ["drug tariff category", "tariff category", "category", "cat"],
    "price": [
        "basic price", "tariff price", "reimbursement price", "price per pack",
        "price", "amount",
    ],
}


def month_of(path: Path) -> str:
    match = re.search(r"(20\d{2})[-_]?([01]\d)", path.stem)
    if not match or not 1 <= int(match[2]) <= 12:
        raise ValueError(f"Filename must contain a valid YYYY-MM month: {path.name}")
    return f"{match[1]}-{match[2]}"


def _normalise(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).replace("\ufeff", "").lower()).strip()


def _find_column(columns, field: str):
    cleaned = [(_normalise(column), column) for column in columns]
    # Prefer exact matches before partial matches to avoid selecting a related
    # but incorrect column such as "Drug name code".
    aliases = [_normalise(name) for name in COLS[field]]
    for alias in aliases:
        for name, original in cleaned:
            if name == alias:
                return original
    for alias in aliases:
        for name, original in cleaned:
            if alias and (name.startswith(alias + " ") or name.endswith(" " + alias)):
                return original
    return None


def _read_csv_candidates(path: Path):
    # NHSBSA downloads may use a title row and occasionally a semicolon delimiter.
    for sep in (None, ";", ",", "\t"):
        for header in range(0, 16):
            try:
                frame = pd.read_csv(
                    path, sep=sep, header=header, engine="python",
                    encoding="utf-8-sig", on_bad_lines="skip",
                )
                if len(frame.columns) > 1:
                    yield frame
            except (UnicodeDecodeError, pd.errors.ParserError, ValueError):
                continue


def _read_excel_candidates(path: Path):
    book = pd.ExcelFile(path)
    for sheet in book.sheet_names:
        for header in range(0, 16):
            try:
                frame = pd.read_excel(book, sheet_name=sheet, header=header)
                if len(frame.columns) > 1:
                    yield frame
            except (ValueError, IndexError):
                continue


def read_table(path: Path, required=("product", "pack", "price")) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        candidates = _read_csv_candidates(path)
    elif suffix in {".xlsx", ".xls"}:
        candidates = _read_excel_candidates(path)
    else:
        raise ValueError("Unsupported file type. Upload a CSV or Excel XLSX file.")

    best = None
    best_score = -1
    for frame in candidates:
        frame.columns = [str(c).strip() for c in frame.columns]
        found = {field: _find_column(frame.columns, field) for field in required}
        score = sum(value is not None for value in found.values())
        if score > best_score:
            best, best_score = (frame, found), score
        if score == len(required):
            return frame

    if best is None:
        raise ValueError("The file could not be read as a table.")
    found = best[1]
    missing = [field for field in required if found.get(field) is None]
    raise ValueError(
        "Could not identify the required columns: " + ", ".join(missing)
        + ". Expected a product/drug name, pack size and price column. "
        "Make sure you uploaded the data table, not a summary or cover sheet."
    )


def _category_column(frame: pd.DataFrame, path: Path):
    column = _find_column(frame.columns, "category")
    if column:
        return frame[column].astype(str).str.extract(r"([ACM])\s*$", expand=False).str.upper()

    # Some official downloads are already split by category and have no category
    # column. Only infer it when the report title explicitly identifies it.
    try:
        if path.suffix.lower() == ".csv":
            preview = path.read_bytes()[:10000].decode("utf-8-sig", errors="ignore").lower()
        else:
            preview_frame = pd.read_excel(path, header=None, nrows=12)
            preview = " ".join(str(value) for value in preview_frame.fillna("").to_numpy().ravel()).lower()
    except (OSError, ValueError, ImportError):
        preview = ""
    match = re.search(r"category\s*([acm])", preview)
    if not match:
        preview = " ".join(str(v) for v in frame.columns).lower()
        match = re.search(r"category\s*([acm])", preview)
    if match:
        return pd.Series(match.group(1).upper(), index=frame.index)
    raise ValueError(
        "Could not identify a tariff category column. If this is a category-specific "
        "file, include the category in its title (for example, Category M)."
    )


def load():
    rows, concessions = [], []
    for path in sorted(RAW.glob("*")):
        if path.suffix.lower() not in {".csv", ".xlsx", ".xls"}:
            continue
        month = month_of(path)
        is_concession = "concession" in path.name.lower()

        if is_concession:
            frame = read_table(path, required=("product",))
            product_col = _find_column(frame.columns, "product")
            concessions.append(pd.DataFrame({
                "month": month,
                "product": frame[product_col].astype(str).str.strip(),
            }))
            continue

        frame = read_table(path)
        product_col = _find_column(frame.columns, "product")
        pack_col = _find_column(frame.columns, "pack")
        price_col = _find_column(frame.columns, "price")
        category = _category_column(frame, path)

        price = frame[price_col].astype(str).str.replace(",", "", regex=False)
        price = price.str.replace(r"[^0-9.()\-]", "", regex=True)
        # Accounting-style negative values, e.g. (12.34), are handled safely.
        price = price.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        numeric_price = pd.to_numeric(price, errors="coerce")
        rows.append(pd.DataFrame({
            "month": month,
            "product": frame[product_col].astype(str).str.strip(),
            "pack": frame[pack_col].astype(str).str.strip(),
            "category": category,
            "price": numeric_price / (100 if PRICE_IN_PENCE else 1),
        }))

    if not rows:
        raise FileNotFoundError("No tariff files found yet. Upload a monthly Drug Tariff file first.")
    prices = pd.concat(rows, ignore_index=True)
    prices = prices[
        prices["product"].notna()
        & prices["pack"].notna()
        & prices["product"].astype(str).str.strip().ne("")
        & prices["product"].astype(str).str.lower().ne("nan")
    ]
    return prices, (
        pd.concat(concessions, ignore_index=True)
        if concessions else pd.DataFrame(columns=["month", "product"])
    )


def build(prices: pd.DataFrame, concessions: pd.DataFrame) -> pd.DataFrame:
    prices = prices.dropna(subset=["price"]).copy()
    prices = prices[prices["category"].isin(list("ACM"))].copy()
    if prices.empty:
        raise ValueError(
            "No usable tariff rows found. Check that the file contains numeric prices "
            "and categories A, C or M."
        )
    prices["key"] = prices["product"] + "|" + prices["pack"]
    prices = prices.drop_duplicates(["month", "key"], keep="last").sort_values(["key", "month"])
    flagged = set(zip(concessions["month"], concessions["product"].astype(str).str.lower()))
    prices["concession"] = [
        (month, product.lower()) in flagged
        for month, product in zip(prices["month"], prices["product"])
    ]
    grouped = prices.groupby("key", sort=False)
    prices["mom_change"] = grouped["price"].pct_change()
    previous_category = grouped["category"].shift()
    prices["category_changed"] = previous_category.notna() & previous_category.ne(prices["category"])
    return prices


def export(prices: pd.DataFrame) -> dict:
    terms = (
        [term.strip().lower() for term in PORTFOLIO.read_text(encoding="utf-8").splitlines() if term.strip()]
        if PORTFOLIO.exists() else []
    )
    months = sorted(prices["month"].unique())
    wide = lambda column: prices.pivot(index="key", columns="month", values=column).reindex(columns=months)
    price = wide("price").ffill(axis=1).bfill(axis=1)
    category = wide("category").ffill(axis=1).bfill(axis=1)
    concession = wide("concession").fillna(False)
    meta = prices.drop_duplicates("key").set_index("key")

    def in_portfolio(key):
        product_name = str(meta.at[key, "product"]).lower()
        return any(term in product_name for term in terms)

    movers = prices.groupby("key")["mom_change"].last().abs().fillna(0).sort_values(ascending=False)
    portfolio_keys = [key for key in price.index if in_portfolio(key)]
    other_keys = [key for key in movers.index if not in_portfolio(key)]
    keys = portfolio_keys + other_keys

    products = []
    for key in keys:
        products.append({
            "n": str(meta.at[key, "product"]),
            "pk": str(meta.at[key, "pack"]),
            "pf": in_portfolio(key),
            "pr": [round(float(value), 2) for value in price.loc[key]],
            "ct": [str(value) for value in category.loc[key]],
            "cn": [bool(value) for value in concession.loc[key]],
        })
    return {
        "months": [pd.to_datetime(month).strftime("%b %y") for month in months],
        "products": products,
    }


def run() -> str:
    prices = build(*load())
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as connection:
        prices.drop(columns="key").to_sql("prices", connection, if_exists="replace", index=False)
    payload = export(prices)
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(OUT)
    return f"Processed {prices['key'].nunique()} products across {prices['month'].nunique()} months."


if __name__ == "__main__":
    print(run())

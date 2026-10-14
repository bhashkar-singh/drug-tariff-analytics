import pandas as pd
import pytest

import pipeline


def test_month_of_requires_valid_month():
    assert pipeline.month_of(pipeline.Path("drug_tariff_2026-10.csv")) == "2026-10"
    with pytest.raises(ValueError):
        pipeline.month_of(pipeline.Path("drug_tariff_2026-13.csv"))


def test_read_table_finds_header_after_title_row(tmp_path):
    path = tmp_path / "drug_tariff_2026-10.csv"
    path.write_text(
        "Category M Prices - October 2026,,,,\n"
        "This is an official data export,,,,\n"
        "Drug Name,Pack Size,Basic Price\n"
        "Example medicine 10mg tablets,28,125.00\n",
        encoding="utf-8",
    )
    frame = pipeline.read_table(path)
    assert list(frame.columns) == ["Drug Name", "Pack Size", "Basic Price"]
    assert frame.iloc[0]["Drug Name"] == "Example medicine 10mg tablets"


def test_load_infers_category_from_category_specific_csv(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "drug_tariff_2026-10.csv").write_text(
        "Category M Prices - October 2026,,,,\n"
        "Drug Name,Pack Size,Basic Price\n"
        "Example medicine 10mg tablets,28,125.00\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline, "RAW", raw)
    prices, concessions = pipeline.load()
    assert prices.iloc[0]["category"] == "M"
    assert prices.iloc[0]["price"] == pytest.approx(1.25)
    assert concessions.empty


def test_build_rejects_empty_usable_data():
    prices = pd.DataFrame([{
        "month": "2026-10", "product": "Example", "pack": "28",
        "category": "X", "price": 1.25,
    }])
    concessions = pd.DataFrame(columns=["month", "product"])
    with pytest.raises(ValueError, match="No usable tariff rows"):
        pipeline.build(prices, concessions)

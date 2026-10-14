"""Illustrative sample data shown until real Drug Tariff files are uploaded."""
import random
from datetime import date

# name, pack size, base price in pounds, in portfolio (sample flag), starting category
D = [["Atorvastatin 20mg tablets","28",1.35,1,"M"],["Amlodipine 5mg tablets","28",.95,0,"M"],["Omeprazole 20mg capsules","28",1.2,1,"M"],["Metformin 500mg tablets","84",1.85,0,"M"],["Sertraline 50mg tablets","28",1.4,1,"M"],["Lansoprazole 30mg capsules","28",1.1,0,"A"],["Levothyroxine 50mcg tablets","28",1.6,0,"A"],["Ramipril 5mg capsules","28",1.25,1,"M"],["Bisoprolol 5mg tablets","28",1.05,0,"M"],["Gabapentin 300mg capsules","100",3.4,1,"C"],["Clopidogrel 75mg tablets","28",1.5,0,"A"],["Montelukast 10mg tablets","28",1.75,1,"M"],["Losartan 50mg tablets","28",1.3,0,"M"],["Tamsulosin 400mcg capsules","30",1.9,0,"C"],["Simvastatin 40mg tablets","28",1.15,0,"M"],["Citalopram 20mg tablets","28",1.0,1,"A"],["Pregabalin 75mg capsules","56",2.6,0,"C"],["Furosemide 40mg tablets","28",.9,0,"M"],["Prednisolone 5mg tablets","28",1.45,0,"A"],["Co-codamol 30/500 tablets","100",2.2,1,"M"]]


def make_sample(n: int = 24) -> dict:
    r = random.Random(2610)
    today, months = date.today(), []
    for i in range(n - 1, -1, -1):
        y, m = today.year, today.month - i
        while m < 1:
            m, y = m + 12, y - 1
        months.append(date(y, m, 1).strftime("%b %y"))
    products = []
    for name, pack, base, pf, cat in D:
        p, pr, ct, cn = base, [], [], []
        for _ in range(n):
            if r.random() < .07:
                cat = r.choice("ACM")
            p = max(.4, p * (1 + (r.random() - .55) * .06))
            k = cat != "C" and r.random() < .08
            cn.append(k)
            ct.append(cat)
            pr.append(round(p * ((1.2 + r.random() * .5) if k else 1), 2))
        products.append({"n": name, "pk": pack, "pf": bool(pf), "pr": pr, "ct": ct, "cn": cn})
    return {"months": months, "products": products}

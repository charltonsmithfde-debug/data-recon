import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
sys.path.insert(0, str(WEB_DIR))

import annuity_engine

print("Fetching slicers...")
slicers = annuity_engine.get_annuity_slicers()
print("Slicers keys:", list(slicers.keys()))
print("Years:", slicers["year"])
print("Businesses:", slicers["business"][:6])

print("\nFetching Overview / Acceptances over time...")
res_p1 = annuity_engine.query_annuity_dashboard("overview", "ROLE_EXECUTIVE_ALL", False, {})
print("KPIs:", res_p1["kpis"])
print("Timeline months count:", len(res_p1["timeline"]["labels"]))

print("\nFetching Top Consultants...")
res_p4 = annuity_engine.query_annuity_dashboard("top_consultants", "ROLE_EXECUTIVE_ALL", False, {})
print("Leaderboard top 3:")
for c in res_p4["leaderboard"][:3]:
    print(" ", c["consultant_name"], "|", c["consultant_business"], "| Quoted:", c["quoted_members"], "| Accepted:", c["accepted_members"])
print("Total row:", res_p4["total_row"])

print("\nFetching Alexforbes summary...")
res_p8 = annuity_engine.query_annuity_dashboard("alexforbes", "ROLE_EXECUTIVE_ALL", False, {})
print("Alexforbes KPIs:", res_p8["kpis"])
print("Alexforbes consultants count:", len(res_p8["consultants"]))

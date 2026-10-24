"""
Second probe for rmp-api: find the REAL Texas A&M College Station listing, check that professor
search stays inside that school, and look at what a professor's reviews contain.
Run:  python3 rmp_probe2.py        (makes about 6-8 requests; paste ALL output to Claude)
"""
import time, traceback
from rmp_api import search_schools, search_professors, get_courses, get_all_ratings

def attrs(o):
    return getattr(o, "__dict__", None) or repr(o)

print("1) Looking for the College Station school listing...")
queries = ["Texas A&M University at College Station", "Texas A&M University College Station",
           "Texas A&M College Station", "TAMU"]
seen = {}
for q in queries:
    try:
        for s in search_schools(q):
            seen[s.legacy_id] = s
    except Exception:
        print(f"  query {q!r} failed"); traceback.print_exc()
    time.sleep(0.5)
rows = sorted(seen.values(), key=lambda s: s.num_ratings or 0, reverse=True)
for s in rows:
    print(f"  id={s.legacy_id:<7} ratings={s.num_ratings!s:<6} {s.name} ({s.city}, {s.state})")

cands = [s for s in rows if "college station" in f"{s.name} {s.city}".lower()]
if not cands:
    raise SystemExit("\nNo school with 'College Station' came back - paste this output to Claude.")
school = cands[0]
print(f"\nUsing: id={school.legacy_id} {school.name} ({school.num_ratings} ratings)")

print("\n2) Does professor search stay inside that school?  searching 'Leyk'...")
profs = search_professors("Leyk", school.id)
for p in profs:
    print(f"  {p.first_name} {p.last_name} | {p.department} | {p.school_name} | {p.num_ratings} ratings")
time.sleep(0.5)

target = next((p for p in profs if p.first_name.lower().startswith("z")), profs[0] if profs else None)
if target:
    print(f"\n3) Courses and reviews for {target.first_name} {target.last_name}")
    try:
        print("  courses:", get_courses(target.id)[:8])
        time.sleep(0.5)
        ratings = get_all_ratings(target.id)
        print(f"  fetched {len(ratings)} reviews")
        for r in ratings[:2]:
            print("  review:", attrs(r))
    except Exception:
        traceback.print_exc()

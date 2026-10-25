Howdy Fall 2026 / MaroonWay grade-name matching

Inputs:
- User-uploaded MaroonWay_Fall2026_Professor_Roster.csv (4,516 rows).
- MaroonWay Data/output/schedule_dataset.csv (20,386 rows).
  This repository documents that file as derived from official A&M grade PDFs;
  this report does not claim it was exported from Anex.

Output: Howdy_Fall2026_MaroonWay_Grade_Name_Candidates.csv
One row per Howdy person and candidate grade-name/campus group; unmatched people
still receive one row. Repeated Howdy names in the output are alternative
candidates, NOT additional professors. All original Howdy columns are retained.

Matching uses normalized surname + first initial (including compound-surname
possibilities), with exact course-code overlap and compatible reported campus
required for a supported candidate. No RMP name or rating is used as identity
evidence. Accents/punctuation are normalized; nicknames and changed surnames
are not guessed. Missing evidence is not evidence of a different person.

unique_supported_candidate_NOT_VERIFIED means one supported candidate with no
other Howdy row claiming that grade-name/campus group through supported evidence.
It is NOT a verified identity. Multiple people in historical grade reports may
share an abbreviated name, even when the current roster has only one candidate.
Campus in the source may be inferred from report units. Extra middle initials
are not treated as verified identity evidence. All outputs require review before
merging grades or replacing database identities.

Other statuses explicitly retain ambiguous, conflicting, name-only and unmatched
cases. Historical grade-course overlap does not prove a Fall 2026 offering.
No grade counts were merged, no source names replaced, and no app/database,
authentication, git commit or remote push was changed.

Reproduce: python Data/match_howdy_roster.py (from the repository root)

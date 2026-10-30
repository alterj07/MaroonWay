-- Key instructors on A&M's own person id.
--
-- Until now an instructor was identified by canonical_key, a normalisation of
-- whatever name a source happened to print. That is why "KIM J" from the grade
-- reports could not be told from nine other Kims, and why most instructors
-- carried no rating: the key could not identify a person.
--
-- A&M's public class search (TEC 51.974) publishes a stable person id with
-- every section. Verified across Fall 2026 and Spring 2027: no id carried two
-- different names, and all 3,619 ids present in both terms kept the identical
-- name. Keying on it means identity stops depending on RateMyProfessors
-- entirely -- if RMP changes its API or disappears, nobody's schedule moves.
--
-- Nullable on purpose. Instructors already loaded from the grade reports have
-- no person id until a public-schedule ingest matches them by name, and an
-- instructor nobody can identify is still an instructor who teaches a class.

alter table instructors add column if not exists person_id bigint;

create unique index if not exists instructors_person_id_key
    on instructors (person_id) where person_id is not null;

-- What the link to RateMyProfessors rested on, kept beside the link itself.
-- A rating shown under someone's name is a claim about a real person, so when
-- it turns out wrong the row has to say what decided it rather than leaving
-- the next person to guess.
alter table instructors add column if not exists rmp_match_basis text;
alter table instructors add column if not exists rmp_match_confidence numeric(4, 3);

comment on column instructors.person_id is
    'A&M public class search instructor id (SWV_CLASS_SEARCH_INSTRCTR_JSON.MORE). Stable across terms.';
comment on column instructors.rmp_match_basis is
    'unique | affinity | ambiguous | no_candidates | unreadable_name';

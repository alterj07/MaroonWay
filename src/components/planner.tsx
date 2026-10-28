"use client";
// The planner UI. Data comes from the backend via src/app/page.tsx, which
// fetches real schedules and maps them into Plan/Course.
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { emptyPlan, normalizeCourseCodes, readSavedPlan } from "@/lib/plans";
import type { CourseSection, SavedSchedule, SectionLock } from "@/lib/api";
import { PlusIcon, SearchIcon } from "@animateicons/react/lucide";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Bot,
  CalendarDays,
  Check,
  ChevronDown,
  Clock3,
  Footprints,
  GraduationCap,
  Heart,
  Info,
  LogIn,
  LogOut,
  MapPin,
  Pin,
  MessageSquareText,
  Moon,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Star,
  Sun,
  X,
} from "lucide-react";
export type Course = {
  code: string;
  prof: string;
  days: number[];
  start: number;
  end: number;
  room: string;
  /** Each actual meeting; omitted only by older saved schedules. */
  meetings?: { day: number; start: number; end: number; room: string }[];
  color: string;
  /** Everything the hover card shows. Null where there is no data to show. */
  section?: string;
  rating?: number | null;
  difficulty?: number | null;
  pctA?: number | null;
  gpa?: number | null;
  campus?: string | null;
  delivery?: string | null;
  honors?: boolean;
  seatsOpen?: number | null;
  /** Reviews behind the rating; under 20 is thin evidence. */
  reviews?: number;
  /** Sections at these exact times taught by someone else. */
  sameTimeAlternatives?: number;
};
export type Student = { email: string; name: string | null };

export type Professor = {
  instructor_id: number | null;
  name: string | null;
  department: string | null;
  adj_rating: number | null;
  adj_difficulty: number | null;
  adj_gpa: number | null;
  pct_a: number | null;
  class_reviews: number;
  professor_reviews: number;
  sections: number;
};

export type ExploreCourse = {
  course_id: number;
  code: string;
  title: string | null;
  credits: string | null;
  honors: boolean;
  prereq_text: string | null;
  level: string | null;
  dept_code: string | null;
  campus: string | null;
  professor_count: number;
  avg_rating: number | null;
  avg_pct_a: number | null;
  professors: Professor[];
};

export type Plan = {
  warnings?: string[];
  /** Why no schedule could be built. Set means this is not a schedule at all. */
  failed?: string;
  /** Why the ranker put it here, in its own words. Empty when nothing was
   *  stated, which is different from "conflict-free" -- `tags` falls back to
   *  generic copy, so it cannot answer "why this one". */
  reasons?: string[];
  /** Days on campus, and minutes spent waiting between classes. What separates
   *  two schedules that share every professor and so score the same. */
  days?: number;
  idle?: number;
  /** An earlier option has this exact timetable; only the staff differ. */
  scored?: boolean;
  id: number;
  name: string;
  subtitle: string;
  score: number;
  rating: string;
  aRate: string;
  gap: string;
  earliest: string;
  tags: string[];
  courses: Course[];
};
const days = ["MON", "TUE", "WED", "THU", "FRI"];
const weekDays = [...days, "SAT", "SUN"];

function courseMeetings(course: Course) {
  return course.meetings ?? course.days.map((day) => ({
    day, start: course.start, end: course.end, room: course.room,
  }));
}
const time = (n: number) => {
  const minutes = Math.round(n * 60),
    h = Math.floor(minutes / 60) % 24,
    m = minutes % 60;
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"}`;
};
/**
 * The shape of a week, at card size.
 *
 * This used to print the course code inside every pill. At eighty pixels tall
 * with five courses the pills overlap and the labels shred each other, so the
 * one thing the card is for -- telling two weeks apart at a glance -- was the
 * thing it could not do. Bars only now: the eye compares silhouettes, and the
 * codes are a hover away and on the full calendar below.
 */
function Mini({ courses }: { courses: Course[] }) {
  // Same rule as the calendar: an online class is not time on campus, and
  // drawing it here would make two weeks look different when they are not.
  const onCampus = courses.filter((c) => c.delivery !== "WEB");
  const onlineCount = courses.length - onCampus.length;
  const meetings = onCampus.flatMap(courseMeetings);
  const visibleDays = weekDays.slice(0, Math.max(5, ...meetings.map((m) => m.day + 1)));
  const startHour = Math.min(8, ...meetings.map((m) => Math.floor(m.start)));
  const endHour = Math.max(22, ...meetings.map((m) => Math.ceil(m.end)));
  return (
    <div className="mini-wrap">
    <div className="mini" style={{
      gridTemplateColumns: `18px repeat(${visibleDays.length}, 1fr)`,
      gridTemplateRows: `13px repeat(${(endHour - startHour) * 4}, minmax(0, 1fr))`,
      height: 79,
      rowGap: 0,
    }}>
      <i />
      {visibleDays.map((d, i) => (
        <b key={d} style={{ gridColumn: i + 2 }}>
          {d[0]}
        </b>
      ))}
      {onCampus.flatMap((c, i) =>
        courseMeetings(c).map((meeting, index) => (
          <span
            key={`${i}-${index}`}
            className={c.color}
            style={{
              gridColumn: meeting.day + 2,
              gridRow: `${Math.floor((meeting.start - startHour) * 4) + 2} / ${Math.ceil((meeting.end - startHour) * 4) + 2}`,
              alignSelf: "stretch",
            }}
            title={`${c.code} · ${c.prof} · ${weekDays[meeting.day]} ${time(meeting.start)}–${time(meeting.end)} · ${meeting.room}`}
          />
        )),
      )}
    </div>
    {onlineCount ? (
      <small className="mini-online">
        + {onlineCount} online
      </small>
    ) : null}
    </div>
  );
}
/**
 * Why there is no schedule, stated plainly.
 *
 * This used to render as a schedule card -- an empty week, dashes for every
 * metric, a "Use this schedule" button and a blurb claiming strong professor
 * ratings -- for a result that does not exist. A student reading that cannot
 * tell a missing course from a timetable clash, and the one thing they need,
 * the reason, was a line of small grey text.
 */
function ScheduleProblem({ reason }: { reason: string }) {
  const missing = reason.match(
    /no sections on record for ([A-Z]+ ?\d+[A-Z]?)/i,
  );
  return (
    <div className="problem">
      <span className="problem-mark">
        <AlertTriangle size={20} />
      </span>
      <h2>No schedule could be built</h2>
      <p>{reason}</p>
      {missing ? (
        <ul className="problem-help">
          <li>
            <b>{missing[1]}</b> has no sections in this term. It may not be
            offered, or the term may not be loaded yet.
          </li>
          <li>Check the course number, or remove it and build again.</li>
        </ul>
      ) : (
        <ul className="problem-help">
          <li>Loosen a preference, or allow a tighter gap between classes.</li>
          <li>Remove one course and build again to see which one conflicts.</li>
        </ul>
      )}
    </div>
  );
}

/**
 * An hour mark for the calendar's left gutter.
 *
 * Not time(): "8:00 AM" wrapped in the 48px column and its second line landed
 * on the next hour's label. The minutes on an hour mark are always :00, so
 * they were only ever noise.
 */
function hourLabel(h: number) {
  const hour = h % 12 || 12;
  return `${hour} ${h >= 12 ? "PM" : "AM"}`;
}

/**
 * What is behind a block, on hover or keyboard focus.
 *
 * A block is a choice of instructor as much as a time, so the numbers that
 * justify the choice -- the rating, how hard it marks, how many A's it gives --
 * belong where the choice is rather than a page away.
 */
function CourseHover({ course, meeting }: {
  course: Course;
  meeting: { day: number; start: number; end: number; room: string };
}) {
  const stat = (v: number | null | undefined, digits = 2) =>
    v === null || v === undefined ? "—" : Number(v).toFixed(digits);
  const share = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${Math.round(Number(v) * 100)}%`;

  const tier = evidenceTier(course.reviews);
  // The shrinkage that produces adj_rating returns the campus mean exactly
  // when a professor has no ratings at all, so the API sends a number either
  // way. Printing it would show every unrated professor the same invented
  // 3.77, which is what made the asterisk look like it was lying.
  const known = [
    tier === "none"
      ? null
      : {
          label: "RMP rating",
          value: `${stat(course.rating)} / 5`,
          className: band(course.rating ?? null),
        },
    tier === "none"
      ? null
      : { label: "Difficulty", value: `${stat(course.difficulty)} / 5`, className: "" },
    course.pctA == null
      ? null
      : { label: "A rate", value: share(course.pctA), className: "" },
    course.gpa == null
      ? null
      : {
          label: "Adjusted GPA",
          value: `${stat(Number(course.gpa) * 4 / 5)} / 4.0`,
          className: "",
        },
  ].filter((entry): entry is { label: string; value: string; className: string } =>
    entry !== null,
  );

  return (
    <div className="hover-card" role="tooltip">
      <b>
        {course.code}
        {course.section ? <em>sec {course.section}</em> : null}
      </b>
      <span className="hover-prof">{course.prof}</span>
      {tier === "solid" ? null : (
        <span className="hover-warn">
          <b className="warn-star">*</b>{" "}
          {tier === "none"
            ? "Nobody has rated this professor, so there is no rating to show. The ranking falls back on the campus average for them."
            : `Only ${course.reviews} review${course.reviews === 1 ? "" : "s"} behind this — a weak signal, and the rating has been pulled toward the campus average because of it.`}
        </span>
      )}
      {(course.sameTimeAlternatives ?? 0) > 0 ? (
        <span className="hover-warn">
          <Info size={12} /> {course.sameTimeAlternatives} other instructor
          {(course.sameTimeAlternatives ?? 0) === 1 ? "" : "s"} teach
          {(course.sameTimeAlternatives ?? 0) === 1 ? "es" : ""} this course at
          these exact times.
        </span>
      ) : null}
      {/* Only what is actually known. A row of em dashes reads as a broken
          page, and a rating printed for a professor nobody has rated is worse
          than blank: it is the campus average wearing their name. */}
      {known.length ? (
        <dl>
          {known.map((entry) => (
            <div key={entry.label}>
              <dt>{entry.label}</dt>
              <dd className={entry.className}>{entry.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <span className="hover-warn">
          No ratings and no grade history for this section yet.
        </span>
      )}
      <footer>
        <span>
          <Clock3 size={11} />
          {time(meeting.start)}–{time(meeting.end)}
        </span>
        <span>
          <MapPin size={11} />
          {meeting.room}
        </span>
        {course.campus ? (
          <span>{CAMPUS_NAMES[course.campus] ?? course.campus}</span>
        ) : null}
        {course.honors ? <span className="hover-flag">Honors</span> : null}
        {course.delivery && course.delivery !== "F2F" ? (
          <span className="hover-flag">{course.delivery}</span>
        ) : null}
      </footer>
    </div>
  );
}

/**
 * The course picker, shared by the landing page and the builder's sidebar.
 *
 * It existed only on the landing page, so adding a course once inside the
 * builder meant typing a code into a bare text field -- a different and worse
 * way to do the same thing, in the same app, a few pixels apart.
 */
function CoursePicker({
  open,
  catalog,
  already,
  onClose,
  onAdd,
}: {
  open: boolean;
  catalog: ExploreCourse[];
  /** Courses already chosen: shown as "Added", not selectable again. */
  already: string[];
  onClose: () => void;
  onAdd: (codes: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  if (!open) return null;

  const close = () => {
    setPicked([]);
    setQuery("");
    onClose();
  };

  return (
    <div className="picker-backdrop" onClick={close}>
      <section className="course-picker" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <span>ADD COURSES</span>
            <h2>What are you taking?</h2>
          </div>
          <button onClick={close}>
            <X size={18} />
          </button>
        </header>
        <div className="picker-search">
          <SearchIcon size={17} duration={1.15} color="currentColor" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search course code or name…"
          />
        </div>
        <div className="picker-results">
          {catalog
            .filter((c) =>
              (c.code + " " + (c.title ?? ""))
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .slice(0, 80)
            .map((c) => (
              <button
                key={c.code}
                className={
                  picked.includes(c.code) || already.includes(c.code)
                    ? "picked"
                    : ""
                }
                disabled={already.includes(c.code)}
                onClick={() =>
                  setPicked((v) =>
                    v.includes(c.code)
                      ? v.filter((x) => x !== c.code)
                      : [...v, c.code],
                  )
                }
              >
                <span>
                  <b>{c.code}</b>
                  <small>
                    {c.title ?? "Untitled"} · {c.professor_count} prof
                    {c.professor_count === 1 ? "" : "s"}
                  </small>
                </span>
                <i>
                  {already.includes(c.code) ? (
                    "Added"
                  ) : picked.includes(c.code) ? (
                    <Check size={15} />
                  ) : (
                    <Plus size={15} />
                  )}
                </i>
              </button>
            ))}
        </div>
        <footer>
          <span>{picked.length} selected</span>
          <button
            disabled={!picked.length}
            onClick={() => {
              onAdd(picked);
              close();
            }}
          >
            Add {picked.length || ""} course{picked.length === 1 ? "" : "s"}
          </button>
        </footer>
      </section>
    </div>
  );
}


/**
 * Pinning one course by hand.
 *
 * The priorities box is prose and prose is inferred: good for "somewhere
 * quiet on Fridays", hopeless for "I want this exact section". Everything
 * chosen here is a hard filter sent as a lock, so the schedule either honours
 * it or says it cannot -- it never quietly ranks around it.
 *
 * The section list is the course's real sections, so nothing offered here can
 * fail to exist.
 */
function CourseLock({
  code,
  label,
  term,
  lock,
  onChange,
  onClose,
  onLoad,
}: {
  code: string;
  label: string;
  term: string;
  lock: SectionLock;
  onChange: (next: SectionLock) => void;
  onClose: () => void;
  onLoad?: (term: string, code: string) => Promise<CourseSection[]>;
}) {
  // Without a loader there is nothing to wait for, so the empty list is the
  // initial state rather than something an effect sets on the first paint.
  const [sections, setSections] = useState<CourseSection[] | null>(
    onLoad ? null : [],
  );
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!onLoad) return;
    let live = true;
    onLoad(term, code)
      .then((rows) => live && setSections(rows))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [onLoad, term, code]);

  const instructors = useMemo(() => {
    const seen = new Map<number, string>();
    for (const row of sections ?? []) {
      if (row.instructor_id != null && row.instructor_name) {
        seen.set(row.instructor_id, row.instructor_name);
      }
    }
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [sections]);

  const set = (patch: Partial<SectionLock>) => onChange({ ...lock, ...patch });
  const dayCodes = ["MON", "TUE", "WED", "THU", "FRI"];
  const chosenDays = lock.days ?? [];

  return (
    <div className="picker-backdrop" onClick={onClose}>
      <section className="lock-panel" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <span>PIN THIS CLASS</span>
            <h2>{label}</h2>
          </div>
          <button onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <p className="lock-note">
          Anything set here is a requirement, not a preference. If nothing fits
          it, you will be told rather than handed something else.
        </p>

        <label className="lock-field">
          <span>Instructor</span>
          <select
            value={lock.instructor_id ?? ""}
            onChange={(e) =>
              set({ instructor_id: e.target.value ? Number(e.target.value) : null })
            }
          >
            <option value="">Anyone</option>
            {instructors.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="lock-field">
          <span>Section</span>
          <select
            value={lock.section_code ?? ""}
            onChange={(e) => set({ section_code: e.target.value || null })}
          >
            <option value="">Any section</option>
            {(sections ?? []).map((row) => (
              <option key={row.section_id} value={row.section_code}>
                {row.section_code}
                {row.meetings.length
                  ? ` · ${row.meetings[0].day} ${row.meetings[0].start}`
                  : " · no set time"}
                {row.instructor_name ? ` · ${row.instructor_name}` : ""}
              </option>
            ))}
          </select>
        </label>

        <div className="lock-field">
          <span>Honors</span>
          <div className="lock-choice">
            {[
              { value: null, text: "Either" },
              { value: true, text: "Honors only" },
              { value: false, text: "No honors" },
            ].map((option) => (
              <button
                key={String(option.value)}
                className={lock.honors === option.value ? "on" : ""}
                onClick={() => set({ honors: option.value })}
              >
                {option.text}
              </button>
            ))}
          </div>
        </div>

        <div className="lock-field">
          <span>May meet on</span>
          <div className="lock-choice">
            {dayCodes.map((day) => (
              <button
                key={day}
                className={chosenDays.includes(day) ? "on" : ""}
                aria-pressed={chosenDays.includes(day)}
                onClick={() =>
                  set({
                    days: chosenDays.includes(day)
                      ? chosenDays.filter((d) => d !== day)
                      : [...chosenDays, day],
                  })
                }
              >
                {day[0] === "T" && day === "THU" ? "R" : day[0]}
              </button>
            ))}
          </div>
        </div>

        <div className="lock-times">
          <label className="lock-field">
            <span>Not before</span>
            <input
              type="time"
              value={lock.earliest ?? ""}
              onChange={(e) => set({ earliest: e.target.value || null })}
            />
          </label>
          <label className="lock-field">
            <span>Not after</span>
            <input
              type="time"
              value={lock.latest ?? ""}
              onChange={(e) => set({ latest: e.target.value || null })}
            />
          </label>
        </div>

        {failed ? (
          <p className="lock-note">
            Could not load this course&rsquo;s sections. Instructor and section
            are unavailable; the rest still work.
          </p>
        ) : null}

        <footer>
          <button onClick={() => onChange({})}>Clear</button>
          <button className="lock-done" onClick={onClose}>
            Done
          </button>
        </footer>
      </section>
    </div>
  );
}

function lockSummary(lock: SectionLock | undefined): string | null {
  if (!lock) return null;
  const parts: string[] = [];
  if (lock.section_code) parts.push(`sec ${lock.section_code}`);
  if (lock.instructor_id != null) parts.push("instructor");
  if (lock.honors === true) parts.push("honors");
  if (lock.honors === false) parts.push("no honors");
  if (lock.days?.length) parts.push(lock.days.map((d) => d[0]).join(""));
  if (lock.earliest) parts.push(`from ${lock.earliest}`);
  if (lock.latest) parts.push(`to ${lock.latest}`);
  return parts.length ? parts.join(" · ") : null;
}

function Calendar({ plan }: { plan: Plan }) {
  // An online class is not a place you have to be. Giving it a slot in the
  // grid made the week look fuller than it is and, worse, made an 8am webinar
  // stretch the whole calendar up an hour for a class nobody travels to. They
  // sit above the week instead, on the days they actually run.
  const onCampus = plan.courses.filter((c) => c.delivery !== "WEB");
  const online = plan.courses.filter((c) => c.delivery === "WEB");
  const anytime = online.filter((c) => courseMeetings(c).length === 0);
  const meetings = onCampus.flatMap(courseMeetings);
  const visibleDays = weekDays.slice(0, Math.max(5, ...meetings.map((m) => m.day + 1)));
  const startHour = Math.min(8, ...meetings.map((m) => Math.floor(m.start)));
  const endHour = Math.max(22, ...meetings.map((m) => Math.ceil(m.end)));
  const hours = Array.from({ length: endHour - startHour }, (_, i) => startHour + i);
  return (
    <div className="cal-scroll">
      {online.length ? (
        <div className="cal-online">
          <div
            className="cal-online-week"
            style={{
              gridTemplateColumns: `var(--cal-gutter) repeat(${visibleDays.length}, 1fr)`,
            }}
          >
            <span className="cal-online-label">Online</span>
            {visibleDays.map((day, index) => {
              const here = online.filter((c) =>
                courseMeetings(c).some((m) => m.day === index),
              );
              return (
                <div key={day} style={{ gridColumn: index + 2 }}>
                  {here.map((c) => (
                    <em
                      key={`${c.code}-${c.section}`}
                      className={c.color}
                      title={`${c.code}${c.prof ? ` · ${c.prof}` : ""} · online${
                        courseMeetings(c)
                          .filter((m) => m.day === index)
                          .map((m) => ` · ${time(m.start)}–${time(m.end)}`)
                          .join("")
                      }`}
                    >
                      {c.code}
                    </em>
                  ))}
                </div>
              );
            })}
          </div>
          {anytime.length ? (
            <p className="cal-online-any">
              No set meeting time:{" "}
              {anytime.map((c) => c.code).join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}
      <div className="cal" style={{
        gridTemplateColumns: `var(--cal-gutter) repeat(${visibleDays.length}, 1fr)`,
        gridTemplateRows: `var(--cal-head) repeat(${hours.length}, var(--cal-row))`,
        height: `calc(var(--cal-head) + ${hours.length} * var(--cal-row))`,
      }}>
        <i />
        {visibleDays.map((d, i) => (
          <header
            key={d}
            style={{ gridColumn: i + 2 }}
          >
            <small>{d}</small>
          </header>
        ))}
        {hours.map((h) => (
          <label key={h} style={{ gridRow: h - startHour + 2 }}>
            {hourLabel(h)}
          </label>
        ))}
        {visibleDays.map((_, d) => (
          <div
            key={d}
            className="lane"
            style={{ gridColumn: d + 2, gridRow: `2 / ${hours.length + 2}` }}
          />
        ))}
        {onCampus.flatMap((c) =>
          courseMeetings(c).map((meeting, index) => {
            const hours = meeting.end - meeting.start;
            return (
              <article
                key={`${c.code}-${c.section}-${index}`}
                className={`${c.color} block`}
                tabIndex={0}
                style={{
                  // Measured off the same custom properties the grid uses, so
                  // changing either cannot leave the blocks beside their
                  // column again -- the offset used to hardcode a gutter width
                  // that the grid had since outgrown.
                  left: `calc(var(--cal-gutter) + ((100% - var(--cal-gutter)) / ${visibleDays.length}) * ${meeting.day})`,
                  width: `calc((100% - var(--cal-gutter)) / ${visibleDays.length} - 6px)`,
                  maxWidth: `calc((100% - var(--cal-gutter)) / ${visibleDays.length} - 6px)`,
                  top: `calc(var(--cal-head) + ${meeting.start - startHour} * var(--cal-row))`,
                  height: `calc(${hours} * var(--cal-row))`,
                }}
              >
                <span className="block-main">
                  <strong>
                    {c.code}
                    {/* Three states, not two: a 4.9 from ninety reviews, a
                        4.9 from three, and no rating at all are three
                        different claims and used to look like two. */}
                    {evidenceTier(c.reviews) === "none" ? (
                      <i
                        className="mark-unrated"
                        title="Nobody has rated this professor — there is no rating behind this one"
                      >
                        ?
                      </i>
                    ) : evidenceTier(c.reviews) === "thin" ? (
                      <i
                        className="mark-thin"
                        title={`Only ${c.reviews} RateMyProfessors review${c.reviews === 1 ? "" : "s"} behind this rating — treat it as a weak signal`}
                      >
                        *
                      </i>
                    ) : null}
                    {/* Another instructor teaches this exact slot. */}
                    {(c.sameTimeAlternatives ?? 0) > 0 ? (
                      <span
                        className="mark-alt"
                        title={`${c.sameTimeAlternatives} other instructor${(c.sameTimeAlternatives ?? 0) === 1 ? "" : "s"} teach${(c.sameTimeAlternatives ?? 0) === 1 ? "es" : ""} this course at exactly these times — the timetable looks the same whichever you take`}
                      >
                        <Info size={13} />
                      </span>
                    ) : null}
                  </strong>
                  {/* The rows are tall enough for three lines at the shortest
                      class A&M timetables, so the time and who teaches it are
                      both on the card rather than only in the hover. Anything
                      shorter still drops them rather than overflowing. */}
                  {hours >= 0.7 ? (
                    <>
                      <span>
                        {time(meeting.start)}–{time(meeting.end)}
                      </span>
                      {c.prof ? (
                        <span className="block-who" title={c.prof}>
                          {c.prof}
                        </span>
                      ) : null}
                    </>
                  ) : null}
                </span>
                {/* The room goes on the right rather than on a third line, so
                    a short class can show it too instead of hiding where it
                    actually is. */}
                {meeting.room ? (
                  <small className="block-where" title={meeting.room}>
                    <MapPin size={10} />
                    {meeting.room}
                  </small>
                ) : null}
                <CourseHover course={c} meeting={meeting} />
              </article>
            );
          }),
        )}
      </div>
    </div>
  );
}
export function Planner({
  plans: initialPlans,
  courses,
  student,
  savedCourses,
  savedWants,
  onSaveCourses,
  onBuildPlans,
  onCourseSections,
  terms,
  initialTerm,
  savedSchedules: initialSavedSchedules = [],
  savedSchedulesError = null,
  serviceError = null,
  onUseSchedule,
}: {
  plans: Plan[];
  courses: ExploreCourse[];
  student: Student | null;
  savedCourses: string[];
  savedWants: string;
  onSaveCourses: (
    codes: string[],
    term?: string | null,
  ) => Promise<{ saved: boolean }>;
  onBuildPlans: (
    codes: string[],
    wants: string,
    term?: string | null,
    locks?: Record<string, SectionLock>,
  ) => Promise<{ plans: Plan[]; relaxed: string[] }>;
  /** Sections of one course, for the pinning panel. Absent in tests. */
  onCourseSections?: (term: string, code: string) => Promise<CourseSection[]>;
  /** Terms with sections loaded, for the semester picker. */
  terms: string[];
  /** The semester used to generate initialPlans on the server. */
  initialTerm?: string | null;
  savedSchedules?: SavedSchedule[];
  savedSchedulesError?: string | null;
  serviceError?: string | null;
  /** Persists a built schedule; what "Use this schedule" means. */
  onUseSchedule: (
    term: string,
    label: string,
    plan: Plan,
  ) => Promise<{ saved: boolean; schedule?: SavedSchedule }>;
}) {
  const [plans, setPlans] = useState<Plan[]>(initialPlans);
  const [savedSchedules, setSavedSchedules] = useState(initialSavedSchedules);
  const savedError = savedSchedulesError;
  const [saveError, setSaveError] = useState<string | null>(null);
  // A failure arrives as one marked plan, not as a list of schedules.
  const failed = plans.length === 1 && Boolean(plans[0].failed);
  // What the student actually asked for, so the builder's sidebar lists their
  // courses rather than the ones in the landing illustration.
  const [chosen, setChosen] = useState<string[]>(savedCourses);
  const build = async (codes: string[], wants: string, selectedTerm = term) => {
    if (busy) return;
    codes = normalizeCourseCodes(codes);
    setChosen(codes);
    setPriorities(wants.split(",").map((s) => s.trim()).filter(Boolean));
    setBusyWhat("build");
    setBusy(true);
    setKept(false);
    setSaveError(null);
    try {
      // Only pins that say something, and only for courses still chosen: an
      // empty lock left behind by a cleared panel would be sent as a
      // constraint that matches everything, and one for a dropped course as a
      // constraint on nothing.
      const pinned = Object.fromEntries(
        Object.entries(locks).filter(
          ([code, lock]) => codes.includes(code) && lockSummary(lock),
        ),
      );
      const result = await onBuildPlans(
        codes,
        wants,
        selectedTerm || null,
        Object.keys(pinned).length ? pinned : undefined,
      );
      setPlans(result.plans);
      setRelaxed(result.relaxed);
      setActive(1);
    } catch {
      setPlans(emptyPlan("Could not build schedules", "Try rebuilding this semester again"));
      setRelaxed([]);
    } finally {
      setBusy(false);
    }
  };
  // The sidebar shows the student's own courses; the showcase is only a
  // stand-in for a first visit when nothing has been chosen yet.
  const sidebar = useMemo(() => {
    if (!chosen.length) return [];
    const byCode = new Map(courses.map((c) => [c.code, c]));
    return chosen.map((code) => {
      const found = byCode.get(code);
      return {
        code,
        label: code.replace(/^([A-Z]+)(\d.*)$/, "$1 $2"),
        title: found?.title ?? null,
        credits: Number.parseInt(found?.credits ?? "", 10),
      };
    });
  }, [chosen, courses]);
  const sidebarCredits = showcaseCreditTotal(sidebar);
  const [page, setPage] = useState<"home" | "planner" | "explore" | "saved">(
      "home",
    ),
    [dark, setDark] = useState(true),
    [active, setActive] = useState(1),
    [chat, setChat] = useState(true),
    [step, setStep] = useState(0),
    // Seeded from what was actually saved, falling back to the shared
    // defaults, so the chips always name the preferences the build used.
    [priorities, setPriorities] = useState<string[]>(
      savedWants
        ? savedWants
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        : [],
    ),
    // Each of these backs a control that previously did nothing.
    [term, setTerm] = useState(initialTerm ?? terms[0] ?? ""),
    [termOpen, setTermOpen] = useState(false),
    [addingCourse, setAddingCourse] = useState(false),
    // The course a student has asked to remove, pending confirmation.
    [confirmDrop, setConfirmDrop] = useState<string | null>(null),
    // What the student pinned by hand, per course, and which panel is open.
    // Kept beside the chosen courses rather than inside them: a pin outlives
    // a rebuild and has to survive one.
    [locks, setLocks] = useState<Record<string, SectionLock>>({}),
    [lockOpen, setLockOpen] = useState<string | null>(null),
    [lockWas, setLockWas] = useState<string>(""),
    [addingPriority, setAddingPriority] = useState(false),
    [priorityDraft, setPriorityDraft] = useState(""),
    [comparing, setComparing] = useState(false),
    [allOptions, setAllOptions] = useState(false),
    [analysing, setAnalysing] = useState(false),
    [busy, setBusy] = useState(false),
    // Preferences the timetable could not honour. Shown rather than swallowed:
    // a schedule that quietly disobeys is worse than one that says it had to.
    [relaxed, setRelaxed] = useState<string[]>(initialPlans[0]?.warnings ?? []),
    [editing, setEditing] = useState<number | null>(null),
    // What the overlay should say: one flag covers building and saving, and an
    // overlay reporting the wrong one is worse than no overlay.
    [busyWhat, setBusyWhat] = useState<"build" | "save">("build"),
    [kept, setKept] = useState(false);

  /** Everything the student has asked for, as one sentence for the decider. */
  const wants = priorities.filter(Boolean).join(", ");

  // Schedules built from the same instructors score identically on every
  // preference about teaching, so three equal badges are correct and
  // unhelpful. Say what does separate them instead of leaving it a mystery.
  const tied =
    plans.length > 1 && plans.every((p) => p.score === plans[0].score);

  async function rebuild(codes = chosen, text = wants, selectedTerm = term) {
    if (!codes.length || busy) return;
    await build(codes, text, selectedTerm);
  }

  async function addCourses(codes: string[]) {
    setAddingCourse(false);
    if (busy) return;
    const next = normalizeCourseCodes([...chosen, ...codes]);
    if (next.length === chosen.length) return;
    await changeCourses(next);
  }

  function addPriority() {
    const text = priorityDraft.trim();
    setPriorityDraft("");
    setAddingPriority(false);
    if (text) setPriorities((v) => [...v, text]);
  }

  async function dropCourse(code: string) {
    setConfirmDrop(null);
    const next = chosen.filter((c) => c !== code);
    await changeCourses(next);
  }

  async function changeCourses(codes: string[]) {
    if (busy) return { saved: false };
    setBusy(true);
    setSaveError(null);
    try {
      const result = await onSaveCourses(codes, term || null);
      if (!result.saved) throw new Error("not saved");
      setChosen(codes);
      setKept(false);
      setActive(1);
      try {
        const result = codes.length ? await onBuildPlans(codes, wants, term || null)
          : { plans: emptyPlan("No classes chosen", "Add the classes you need"), relaxed: [] };
        setPlans(result.plans);
        setRelaxed(result.relaxed);
      } catch {
        setPlans(emptyPlan("Classes saved, schedule unavailable", "Your classes were saved. Try rebuilding your schedule again."));
        setRelaxed([]);
      }
      return result;
    } catch {
      setPlans(emptyPlan("Could not update classes", "Please try updating your classes again"));
      setRelaxed([]);
      setSaveError("Could not update your classes. Please try again.");
      return { saved: false };
    } finally {
      setBusy(false);
    }
  }
  const plan = useMemo(
    () => plans.find((p) => p.id === active) ?? plans[0],
    [active, plans],
  );

  function selectPlan(id: number) {
    if (busy || id === active) return;
    setActive(id);
    setKept(false);
    setSaveError(null);
  }

  async function keepSchedule() {
    if (busy || kept || !term || plan.failed) return;
    setBusyWhat("save");
    setBusy(true);
    setSaveError(null);
    try {
      const result = await onUseSchedule(term, plan.name, plan);
      if (!result.saved) {
        setSaveError("Sign in again to save your schedule.");
        return;
      }
      if (result.schedule) {
        const record = result.schedule;
        setSavedSchedules((previous) => [record, ...previous.filter((s) => s.id !== record.id)]);
      }
      setKept(true);
      setPage("saved");
    } catch {
      setSaveError("Could not save your schedule. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  const prompts = [
      {
        q: "When do you prefer your first class?",
        a: ["8:00 AM", "9:00 AM", "10:00 AM", "After 11 AM"],
      },
      {
        q: "What matters most to you?",
        a: [
          "Best professors",
          "Higher grade averages",
          "Fewer exams",
          "Less walking",
        ],
      },
      {
        q: "How packed should your week feel?",
        a: ["Spread it out", "Balanced", "Compact days", "Surprise me"],
      },
    ],
    prompt = prompts[step];
  if (page === "home")
    return (
      <Landing
        onStart={() => setPage("planner")}
        onSaved={() => setPage("saved")}
        dark={dark}
        setDark={setDark}
        catalog={courses}
        student={student}
        savedCourses={chosen}
        savedWants={wants}
        onBuild={build}
        serviceError={serviceError}
      />
    );
  if (page === "explore")
    return (
      <Explorer
        onNav={setPage}
        dark={dark}
        setDark={setDark}
        courses={courses}
        student={student}
        savedCourses={chosen}
        onSaveCourses={changeCourses}
      />
    );
  if (page === "saved")
    return (
      <SavedSchedules
        onNav={setPage}
        schedules={savedSchedules}
        error={savedError}
        busy={busy}
        onOpen={(record, snapshot) => {
          if (busy) return;
          setPlans([snapshot]);
          setRelaxed(snapshot.warnings ?? []);
          setActive(snapshot.id);
          setTerm(record.term);
          setChosen(snapshot.courses.map((c) => c.code.replace(/\s+/g, "").toUpperCase()));
          setKept(true);
          setSaveError(null);
          setPage("planner");
        }}
        dark={dark}
        setDark={setDark}
        student={student}
      />
    );
  return (
    <main className={`app-page ${dark ? "site-dark" : "site-light"}`}>
      {/* A rebuild walks a large combination space and calls the decider, so
          it can take seconds. Without this the only sign of life is a button
          reading "Rebuilding...", which looks the same as a button that has
          hung. */}
      {busy ? (
        <div className="working" role="status" aria-live="polite">
          <div className="working-card">
            <span className="working-spin" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <b>
              {busyWhat === "save"
                ? "Saving this schedule…"
                : "Building your schedule…"}
            </b>
            <p>
              {busyWhat === "save"
                ? "Keeping it against your account so it is here next time."
                : "Comparing every conflict-free way to take these classes, then ranking them against what you asked for."}
            </p>
          </div>
        </div>
      ) : null}
      <NavRail
        page="planner"
        onNav={setPage}
        student={student}
        dark={dark}
        setDark={setDark}
      />
      <div className="work builder-work">
        <aside className="filters">
          <div className="filter-title">
            <b>
              <SlidersHorizontal size={17} /> Your preferences
            </b>
            <button
              onClick={() => {
                setPriorities([]);
                void rebuild(chosen, "");
              }}
            >
              Reset
            </button>
          </div>
          {/*
            A dropdown of our own rather than a <select>: the option list of a
            native select is drawn by the operating system, so its white
            background and blue highlight cannot be styled to match anything.
          */}
          <div className="term-picker">
            <button
              className="term"
              role="combobox"
              aria-label="Semester"
              aria-controls="semester-options"
              aria-haspopup="listbox"
              aria-expanded={termOpen}
              disabled={!terms.length || !chosen.length || busy}
              onClick={() => setTermOpen((v) => !v)}
            >
              <span>
                <CalendarDays size={17} />
                <i>
                  <small>SEMESTER</small>
                  <b>{term || "No term loaded"}</b>
                </i>
              </span>
              <ChevronDown size={16} className={termOpen ? "flip" : ""} />
            </button>
            {termOpen ? (
              <>
                {/* Catches the click that dismisses the list, so it closes
                    like any other menu rather than only on a second click of
                    the button. */}
                <div className="term-shade" onClick={() => setTermOpen(false)} />
                <ul id="semester-options" className="term-list" role="listbox" aria-label="Semester">
                  {[...new Set([term, ...terms])].filter(Boolean).map((t) => (
                    <li key={t}>
                      <button
                        role="option"
                        aria-selected={t === term}
                        className={t === term ? "chosen" : ""}
                        onClick={() => {
                          setTermOpen(false);
                          if (t === term) return;
                          setTerm(t);
                          void rebuild(chosen, wants, t);
                        }}
                      >
                        {t}
                        {t === term ? <Check size={14} /> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
          <div className="label">
            <b>COURSES · {sidebarCredits} CREDITS</b>
            <button onClick={() => setAddingCourse((v) => !v)}>
              <Plus size={13} /> Add
            </button>
          </div>
          {confirmDrop ? (
            <div
              className="confirm-backdrop"
              onClick={() => setConfirmDrop(null)}
            >
              <div
                className="confirm"
                role="alertdialog"
                aria-modal="true"
                onClick={(e) => e.stopPropagation()}
              >
                <b>
                  Remove {confirmDrop.replace(/^([A-Z]+)(\d.*)$/, "$1 $2")}?
                </b>
                <p>
                  It comes out of this schedule and out of your saved courses.
                  You can add it again from the picker.
                </p>
                <div>
                  <button
                    className="confirm-cancel"
                    autoFocus
                    onClick={() => setConfirmDrop(null)}
                  >
                    Keep it
                  </button>
                  <button
                    className="confirm-go"
                    onClick={() => void dropCourse(confirmDrop)}
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ) : null}
          <CoursePicker
            open={addingCourse}
            catalog={courses}
            already={chosen}
            onClose={() => setAddingCourse(false)}
            onAdd={(codes) => void addCourses(codes)}
          />
          {sidebar.map((c, i) => {
            const pinned = lockSummary(locks[c.code]);
            return (
              <div className="course" key={c.code}>
                <i className={SHOWCASE_COLORS[i % SHOWCASE_COLORS.length]} />
                <span>
                  <b>{c.label}</b>
                  {/* The pin replaces the title when there is one: what you
                      required of this class matters more here than its name,
                      which is already on every block in the week. */}
                  <small>{pinned ?? c.title ?? "Untitled"}</small>
                </span>
                <button
                  className={`course-pin${pinned ? " on" : ""}`}
                  disabled={busy}
                  aria-label={`Pin ${c.label}`}
                  title={pinned ? `Pinned: ${pinned}` : "Pin a section, instructor or time"}
                  onClick={() => {
                    setLockWas(JSON.stringify(locks[c.code] ?? {}));
                    setLockOpen(c.code);
                  }}
                >
                  <Pin size={13} />
                </button>
                <button
                  className="course-drop"
                  disabled={busy}
                  aria-label={`Remove ${c.label}`}
                  onClick={() => setConfirmDrop(c.code)}
                >
                  <X size={13} />
                </button>
              </div>
            );
          })}
          {lockOpen ? (
            <CourseLock
              code={lockOpen}
              label={lockOpen.replace(/^([A-Z]+)(\d.*)$/, "$1 $2")}
              term={term}
              lock={locks[lockOpen] ?? {}}
              onLoad={onCourseSections}
              onChange={(next) =>
                setLocks((all) => ({ ...all, [lockOpen]: next }))
              }
              onClose={() => {
                const now = JSON.stringify(locks[lockOpen] ?? {});
                setLockOpen(null);
                // Rebuild only when something actually changed. Opening a
                // panel to look and closing it should not spend a build.
                if (now !== lockWas) void rebuild();
              }}
            />
          ) : null}
          <div className="label priority-label">
            <b>PRIORITIES</b>
            <button onClick={() => setAddingPriority((v) => !v)}>
              <Plus size={13} /> Add
            </button>
          </div>
          {addingPriority ? (
            <input
              className="side-add"
              autoFocus
              value={priorityDraft}
              placeholder="e.g. nothing before 10am"
              onChange={(e) => setPriorityDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addPriority();
                if (e.key === "Escape") setAddingPriority(false);
              }}
              onBlur={addPriority}
            />
          ) : null}
          <div className="chips">
            {priorities.map((p, i) =>
              editing === i ? (
                <input
                  key={p}
                  className="side-add"
                  autoFocus
                  defaultValue={p}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setEditing(null);
                    if (e.key !== "Enter") return;
                    const text = e.currentTarget.value.trim();
                    setEditing(null);
                    setPriorities((v) =>
                      text
                        ? v.map((old, x) => (x === i ? text : old))
                        : v.filter((_, x) => x !== i),
                    );
                  }}
                  onBlur={(e) => {
                    const text = e.currentTarget.value.trim();
                    setEditing(null);
                    setPriorities((v) =>
                      text
                        ? v.map((old, x) => (x === i ? text : old))
                        : v.filter((_, x) => x !== i),
                    );
                  }}
                />
              ) : (
                /* The chip edits; the × deletes. Clicking the body used to
                   delete it, so correcting a word meant retyping the lot. */
                <span className="chip" key={p}>
                  <button
                    className="chip-edit"
                    title="Edit this priority"
                    onClick={() => setEditing(i)}
                  >
                    <Check size={12} />
                    {p}
                  </button>
                  <button
                    className="chip-drop"
                    aria-label={`Remove "${p}"`}
                    onClick={() =>
                      setPriorities((v) => v.filter((_, x) => x !== i))
                    }
                  >
                    <X size={11} />
                  </button>
                </span>
              ),
            )}
          </div>
          <p className="analysis-note">Describe your preferred week in the priorities above, then rebuild.</p>
          <button
            className="rebuild"
            disabled={busy || !chosen.length}
            onClick={() => void rebuild()}
          >
            <Sparkles size={15} />{" "}
            {busy ? "Rebuilding…" : "Rebuild my schedule"}
          </button>
        </aside>
        <section className="results">
          <div className="result-title">
            <span>
              <small>{failed ? "RESULT" : "TOP RECOMMENDATIONS"}</small>
              <h2>
                {failed
                  ? "No schedules"
                  : `${plans.length} schedule${plans.length === 1 ? "" : "s"} built for you`}
              </h2>
              {!failed && plans.length > 3 ? (
                <small className="tied-note">
                  {allOptions ? "Showing all options." : "Showing the best three."}{" "}
                  <button className="link" onClick={() => setAllOptions((v) => !v)}>
                    {allOptions ? "Show top three" : `Show all ${plans.length} options`}
                  </button>
                </small>
              ) : null}
              {relaxed.length ? (
                <p className="caution" role="status">
                  <AlertTriangle size={14} />
                  <span>
                    {relaxed.join("; ")} — these schedules are the closest fit
                    without it.
                  </span>
                </p>
              ) : null}
              {tied ? (
                <small className="tied-note">
                  Same professors in each, so they score the same on what you
                  asked for. They differ in timing.
                </small>
              ) : null}
            </span>
            {failed ? null : (
              <button onClick={() => setComparing((v) => !v)}>
                <SlidersHorizontal size={14} />{" "}
                {comparing ? "Hide comparison" : "Compare"}
              </button>
            )}
          </div>
          <div className="cards">
            {/* Built candidates stay separate from schedules saved to the account. */}
            {(failed ? [] : allOptions ? plans : plans.slice(0, 3)).map((p, i) => (
              <button
                key={p.id}
                disabled={busy}
                onClick={() => selectPlan(p.id)}
                className={active === p.id ? "selected" : ""}
              >
                <div>
                  <strong>
                    {i === 0 ? <Sparkles size={14} /> : "#" + (i + 1)}
                  </strong>
                  {/* A percentage is only worth printing when there was
                      something to score against. With no stated priorities
                      every option scores the same defaults, and three cards
                      reading "48% match" say nothing three times. */}
                  {p.scored ? <em>{p.score}% match</em> : null}
                </div>
                <h3>{p.name}</h3>
                <p>
                  {!p.scored || (tied && p.idle !== undefined)
                    ? `${p.days ?? "?"} days on campus · ${Math.round((p.idle ?? 0) / 60)}h waiting`
                    : p.subtitle}
                </p>
                <Mini courses={p.courses} />
                <footer>
                  <span>
                    <Star size={12} />
                    {p.rating}
                  </span>
                  <span>
                    <GraduationCap size={12} />
                    {p.aRate} A’s
                  </span>
                  <span>
                    <Clock3 size={12} />
                    {p.gap}
                  </span>
                </footer>
              </button>
            ))}
          </div>
          {comparing && !failed ? (
            <table className="compare">
              <thead>
                <tr>
                  <th>Option</th>
                  <th>Match</th>
                  <th>Professor avg.</th>
                  <th>A rate</th>
                  <th>Tightest gap</th>
                  <th>Earliest</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((p) => (
                  <tr
                    key={p.id}
                    className={p.id === active ? "is-active" : ""}
                    onClick={() => selectPlan(p.id)}
                  >
                    <td>{p.name}</td>
                    <td>{p.score}%</td>
                    <td>{p.rating}</td>
                    <td>{p.aRate}</td>
                    <td>{p.gap}</td>
                    <td>{p.earliest}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          <div className="detail">
            {plan.failed ? (
              <ScheduleProblem reason={plan.failed} />
            ) : (
              <>
            <div className="detail-head">
              <span>
                <em>
                  <Sparkles size={11} /> BEST MATCH
                </em>
                <h2>{plan.name}</h2>
                <p>{plan.tags.join(" · ")}</p>
              </span>
              <div>
                <button className="save" aria-label={kept ? "Schedule saved" : "Save schedule"}
                  disabled={busy || kept || !term} onClick={() => void keepSchedule()}>
                  <Heart size={17} fill={kept ? "currentColor" : "none"} />
                </button>
                <button
                  className="use"
                  disabled={busy || kept || !term}
                  onClick={() => void keepSchedule()}
                >
                  {kept ? "Saved" : "Use this schedule"}{" "}
                  <ArrowRight size={15} />
                </button>
              </div>
            </div>
            {saveError && <p role="alert">{saveError}</p>}
            {plan.warnings?.map((warning) => <p role="status" key={warning}>{warning}</p>)}
            <div className="metrics">
              <Metric
                icon={<Star />}
                label="PROFESSOR AVG."
                value={`${plan.rating} / 5.0`}
              />
              <Metric
                icon={<GraduationCap />}
                label="AVERAGE A RATE"
                value={plan.aRate}
              />
              <Metric icon={<Clock3 />} label="TIGHTEST GAP" value={plan.gap} />
              <Metric
                icon={<Clock3 />}
                label="EARLIEST CLASS"
                value={plan.earliest}
              />
            </div>
            <Calendar plan={plan} />
            <div className="why">
              <span>
                <Bot size={18} />
              </span>
              <div>
                <b>Why this works for you</b>
                {/* The reasons the ranker actually gave. This was a fixed
                    sentence claiming "no Friday classes" about every schedule,
                    including ones with a Friday class in them. */}
                <p>
                  {plan.reasons?.length
                    ? `Ranked on ${plan.reasons.join(", ")}.`
                    : "You have not said what you want yet, so this is ranked on professor rating, then on difficulty."}
                </p>
              </div>
              <button onClick={() => setAnalysing((v) => !v)}>
                {analysing ? "Hide analysis" : "View full analysis"}{" "}
                <ArrowRight size={13} />
              </button>
            </div>
            {analysing ? (
              <div className="analysis">
                <h3>Every class in this schedule</h3>
                <table>
                  <thead>
                    <tr>
                      <th>Class</th>
                      <th>Professor</th>
                      <th>Rating</th>
                      <th>Difficulty</th>
                      <th>A rate</th>
                      <th>When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.courses.map((c) => (
                      <tr key={c.code}>
                        <td>
                          <b>{c.code}</b>
                          {c.section ? <em> sec {c.section}</em> : null}
                        </td>
                        <td>{c.prof}</td>
                        <td className={band(c.rating ?? null)}>
                          {c.rating === null || c.rating === undefined
                            ? "—"
                            : Number(c.rating).toFixed(2)}
                        </td>
                        <td>
                          {c.difficulty === null || c.difficulty === undefined
                            ? "—"
                            : Number(c.difficulty).toFixed(2)}
                        </td>
                        <td>
                          {c.pctA === null || c.pctA === undefined
                            ? "—"
                            : `${Math.round(Number(c.pctA) * 100)}%`}
                        </td>
                        <td>
                          {courseMeetings(c).map((meeting, index) => (
                            <div key={index}>
                              {weekDays[meeting.day]} {time(meeting.start)}–{time(meeting.end)} · {meeting.room}
                            </div>
                          ))}
                          {!courseMeetings(c).length && (c.delivery === "WEB" ? "Online · Asynchronous" : "Meeting times TBA")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="analysis-note">
                  Ratings are shrunk toward the average by how few reviews a
                  professor has, so one glowing review does not outrank eighty
                  steady ones. Ties break on difficulty, lowest first.
                </p>
              </div>
            ) : null}
              </>
            )}
          </div>
        </section>
      </div>

    </main>
  );
}
/* eslint-disable @next/next/no-html-link-for-pages */
/**
 * Sign in, or who you are signed in as.
 *
 * This corner used to be a hardcoded avatar reading "JK / Joshua" with no
 * handler, which is why none of it could be clicked. Real <a> links, not
 * <Link>: NextAuth's routes return HTML pages, so a client-side navigation to
 * them would try to fetch an RSC payload and fail.
 */
function Account({ student }: { student?: Student | null }) {
  if (!student)
    return (
      <a
        className="account-link"
        href="/api/auth/signin?callbackUrl=/"
        title="Sign in with your tamu.edu Google account"
      >
        <LogIn size={16} /> Sign in
      </a>
    );
  const label = (student.name || student.email).trim();
  const initials = label
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
  return (
    <>
      <span title={student.email}>{initials}</span>
      <div>
        <b>{student.name || label.split("@")[0]}</b>
        <small>{student.email}</small>
      </div>
      <a
        className="account-link"
        href="/api/auth/signout?callbackUrl=/"
        title="Sign out"
      >
        <LogOut size={16} />
      </a>
    </>
  );
}
/* eslint-enable @next/next/no-html-link-for-pages */

/**
 * Navigation, as a rail down the left that opens on hover.
 *
 * One component for every view, including the landing page, which previously
 * had a header of its own that shared nothing with the others -- so the same
 * three destinations looked and sat differently depending on where you were.
 *
 * Collapsed it is icons only; hovering or tabbing into it reveals the labels.
 * `focus-within` matters as much as `:hover` here: a rail that only answers to
 * a mouse cannot be navigated by keyboard.
 */
function NavRail({
  page,
  onNav,
  student,
  dark,
  setDark,
}: {
  page: "home" | "planner" | "explore" | "saved";
  onNav: (p: "home" | "planner" | "explore" | "saved") => void;
  student?: Student | null;
  dark: boolean;
  setDark: (v: boolean) => void;
}) {
  const items: {
    key: "planner" | "explore" | "saved";
    label: string;
    icon: ReactNode;
  }[] = [
    {
      key: "planner",
      label: "Schedule builder",
      icon: <CalendarDays size={18} />,
    },
    { key: "explore", label: "Course explorer", icon: <BookOpen size={18} /> },
    { key: "saved", label: "Saved schedules", icon: <Heart size={18} /> },
  ];

  const label = (student?.name || student?.email || "").trim();
  const initials = label
    ? label
        .split(/[\s@.]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((w) => w[0]!.toUpperCase())
        .join("")
    : "";

  return (
    <nav className="rail" aria-label="Main">
      <button className="rail-brand" onClick={() => onNav("home")}>
        <span>
          <CalendarDays size={19} />
        </span>
        <b>MaroonWay</b>
      </button>

      <ul>
        {items.map((item) => (
          <li key={item.key}>
            <button
              className={page === item.key ? "active" : ""}
              aria-current={page === item.key ? "page" : undefined}
              onClick={() => onNav(item.key)}
            >
              {item.icon}
              <b>{item.label}</b>
            </button>
          </li>
        ))}
      </ul>

      <div className="rail-foot">
        <button
          onClick={() => setDark(!dark)}
          aria-label={`Switch to ${dark ? "light" : "dark"} mode`}
        >
          {dark ? <Sun size={17} /> : <Moon size={17} />}
          <b>{dark ? "Light mode" : "Dark mode"}</b>
        </button>

        {student ? (
          <>
            <span className="rail-me" title={student.email}>
              <i>{initials}</i>
              <b>{student.name || label.split("@")[0]}</b>
            </span>
            {/* A real <a>: NextAuth's routes return HTML pages, so a
                client-side navigation would fetch an RSC payload and fail. */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a href="/api/auth/signout?callbackUrl=/" title="Sign out">
              <LogOut size={17} />
              <b>Sign out</b>
            </a>
          </>
        ) : null}
      </div>
    </nav>
  );
}

function band(rating: number | string | null) {
  const value = num(rating);
  if (value === null) return "prof-unrated";
  if (value >= 4.2) return "prof-great";
  if (value >= 3.6) return "prof-good";
  if (value >= 3.0) return "prof-mixed";
  return "prof-poor";
}

/** CSTAT / GALV / QATAR as a student would say them. */
/**
 * A few real courses to illustrate with.
 *
 * The builder sidebar and the landing calendar both used to name four
 * hardcoded codes. They now take the first few catalogue courses with enough
 * instructors to be worth ranking, so the illustrations cannot drift from the
 * data behind them.
 */
function showcaseCourses(catalog: ExploreCourse[], count = 4) {
  return catalog
    .filter((c) => c.professor_count >= 2 && c.title)
    .slice(0, count)
    .map((c) => ({
      code: c.code,
      label: c.code.replace(/^([A-Z]+)(\d.*)$/, "$1 $2"),
      title: c.title,
      credits: Number.parseInt(c.credits ?? "", 10),
    }));
}

function showcaseCreditTotal(showcase: { credits: number }[]) {
  return showcase.reduce(
    (total, c) => total + (Number.isFinite(c.credits) ? c.credits : 3),
    0,
  );
}

/** Colour classes and clock labels for the landing illustration, cycled over
 *  whatever courses the catalogue supplies. */
const SHOWCASE_COLORS = ["berry", "blue", "green", "gold", "purple"];
const SHOWCASE_TIMES = ["9:35", "9:35", "11:30", "12:45", "14:20"];

/** Monday-first, matching the calendar's own day order. */
const DAY_LETTERS = ["M", "T", "W", "R", "F", "S", "U"];

/** Below this many reviews, a rating is marked as thin evidence. */
const THIN_EVIDENCE = 20;

/** How much is actually known about who teaches a section.
 *
 * "No ratings" and "two ratings" were sharing one asterisk, which made the
 * warning read as wrong whenever a number appeared beside it -- and a number
 * always appears, because the shrinkage returns the campus mean for a
 * professor nobody has rated.
 */
type Evidence = "none" | "thin" | "solid";

function evidenceTier(reviews: number | null | undefined): Evidence {
  const count = reviews ?? 0;
  if (count === 0) return "none";
  return count < THIN_EVIDENCE ? "thin" : "solid";
}
const CAMPUS_NAMES: Record<string, string> = {
  CSTAT: "College Station",
  GALV: "Galveston",
  QATAR: "Qatar",
  BLINN: "Blinn",
};

/**
 * Scores arrive as numbers, except where Postgres computed them with avg(),
 * which returns numeric and serialises as a string. One of those reaching
 * .toFixed() took the whole explorer down with "v.toFixed is not a function",
 * so these coerce rather than trust the declared type.
 */
function num(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const pct = (v: number | string | null) => {
  const n = num(v);
  return n === null ? "—" : `${Math.round(n * 100)}%`;
};
const score = (v: number | string | null) => {
  const n = num(v);
  return n === null ? "—" : n.toFixed(2);
};

/**
 * The professors who teach a course, named on the card itself.
 *
 * This is the explorer's whole point: a student choosing CSCE 121 is really
 * choosing an instructor, so the names and their ratings belong on the card
 * rather than one click away.
 */
function Professors({
  professors,
  limit = 4,
}: {
  professors: Professor[];
  limit?: number;
}) {
  if (!professors.length)
    return <small className="prof-none">No instructor data yet</small>;
  const shown = professors.slice(0, limit);
  return (
    <ul className="prof-chips">
      {shown.map((p) => (
        <li
          key={p.instructor_id ?? p.name}
          className={band(p.adj_rating)}
          title={[
            `${p.name}: rating ${score(p.adj_rating)}`,
            `difficulty ${score(p.adj_difficulty)}`,
            `${pct(p.pct_a)} A's`,
            p.department,
          ]
            .filter(Boolean)
            .join(", ")}
        >
          <b>{p.name}</b>
          <em>{score(p.adj_rating)}</em>
        </li>
      ))}
      {professors.length > shown.length ? (
        <li className="prof-more">+{professors.length - shown.length} more</li>
      ) : null}
    </ul>
  );
}

function Explorer({
  onNav,
  dark,
  setDark,
  courses,
  student,
  savedCourses,
  onSaveCourses,
}: {
  onNav: (p: "home" | "planner" | "explore" | "saved") => void;
  dark: boolean;
  setDark: (value: boolean) => void;
  courses: ExploreCourse[];
  student: Student | null;
  savedCourses: string[];
  /** Saves through the builder so the current schedule stays in sync. */
  onSaveCourses: (codes: string[]) => Promise<{ saved: boolean }>;
}) {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<ExploreCourse | null>(
    courses[0] ?? null,
  );
  // The builder's own list, not a copy taken when this page opened: adding
  // here has to reach the schedule, and a copy would drift from it.
  const added = savedCourses;
  const [saving, setSaving] = useState(false);
  const [courseError, setCourseError] = useState<string | null>(null);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const compact = needle.replace(/\s+/g, "");
    const matches = !needle
      ? courses
      : courses.filter(
          (c) =>
            c.code.toLowerCase().includes(compact) ||
            (c.title ?? "").toLowerCase().includes(needle) ||
            c.professors.some((p) => (p.name ?? "").toLowerCase().includes(needle)),
        );
    // The classes already in the plan first. This page is mostly read while
    // deciding between sections of a course you have chosen, and hunting for
    // it in an alphabetical list of every course at A&M is the slow way to
    // answer a question you came here with. Relative order is otherwise
    // untouched, so nothing moves except to the top.
    const inPlan = new Set(added);
    return [
      ...matches.filter((c) => inPlan.has(c.code)),
      ...matches.filter((c) => !inPlan.has(c.code)),
    ];
  }, [q, courses, added]);

  const active =
    selected && shown.some((c) => c.code === selected.code)
      ? selected
      : (shown[0] ?? null);

  async function toggle(code: string) {
    if (saving) return;
    const next = added.includes(code) ? added.filter((x) => x !== code) : [...added, code];
    setSaving(true);
    setCourseError(null);
    try {
      const result = await onSaveCourses(next);
      if (!result.saved) throw new Error("not saved");
    } catch {
      setCourseError("Could not update your classes. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className={`inner-page ${dark ? "site-dark" : "site-light"}`}>
      <NavRail
        page="explore"
        onNav={onNav}
        student={student}
        dark={dark}
        setDark={setDark}
      />
      <section className="page-wrap">
        <div className="page-intro">
          <span>COURSE INTELLIGENCE</span>
          <h1>Know the class before you take it.</h1>
          <p>
            Every instructor who has taught it, ranked from real grade data and
            RateMyProfessors.
          </p>
        </div>
        <div className="explore-search">
          <SearchIcon size={18} duration={1.15} color="currentColor" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by course, title, or professor…"
          />
          <span className="explore-count">{shown.length} courses</span>
        </div>
        {courses.length === 0 ? (
          <div className="explore-empty">
            <b>No course data loaded.</b>
            <span>
              Run the ingest loaders against a configured database, then reload.
            </span>
          </div>
        ) : null}
        <div className="explore-layout">
          <div className="course-list">
            {shown.slice(0, 120).map((c) => (
              <button
                className={active?.code === c.code ? "selected" : ""}
                key={c.code}
                onClick={() => setSelected(c)}
              >
                <span>
                  <b>{c.code}</b>
                  <small>{c.title ?? "Untitled"}</small>
                  <Professors professors={c.professors} />
                </span>
                <div>
                  <em>
                    <Star size={12} />
                    {score(c.avg_rating)}
                  </em>
                  <strong>
                    {c.professor_count} prof{c.professor_count === 1 ? "" : "s"}
                  </strong>
                  <ArrowRight size={15} />
                </div>
              </button>
            ))}
          </div>
          {active ? (
            <aside className="course-detail">
              <div className="detail-code">
                <span>{active.code}</span>
                <em>{active.credits ?? "—"} CREDITS</em>
                {active.level ? <em>{active.level.toUpperCase()}</em> : null}
                {active.campus ? (
                  <em>
                    {(
                      CAMPUS_NAMES[active.campus] ?? active.campus
                    ).toUpperCase()}
                  </em>
                ) : null}
              </div>
              <h2>{active.title ?? "Untitled"}</h2>
              {active.professors[0]?.department ? (
                <p className="detail-dept">{active.professors[0].department}</p>
              ) : null}
              <div className="insight-grid">
                <Metric
                  icon={<Star />}
                  label="AVG. RATING"
                  value={`${score(active.avg_rating)} / 5`}
                />
                <Metric
                  icon={<GraduationCap />}
                  label="A RATE"
                  value={pct(active.avg_pct_a)}
                />
                <Metric
                  icon={<BookOpen />}
                  label="INSTRUCTORS"
                  value={String(active.professor_count)}
                />
              </div>
              <div className="prof-table">
                <h3>Who teaches it</h3>
                {active.professors.length === 0 ? (
                  <p className="prof-none">
                    No instructor data for this course yet.
                  </p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>Professor</th>
                        <th>Rating</th>
                        <th>Diff.</th>
                        <th>A rate</th>
                        <th>Reviews</th>
                      </tr>
                    </thead>
                    <tbody>
                      {active.professors.map((p) => {
                        // What this row is actually claiming. A rating built
                        // from reviews of *this* class is the thing a student
                        // choosing this class wants; the professor's overall
                        // average is a weaker answer to the same question and
                        // has to say so. The campus mean is neither, and
                        // belongs on a professor's own page, not here.
                        const forClass = p.class_reviews > 0;
                        const tier = evidenceTier(
                          Math.max(p.class_reviews, p.professor_reviews),
                        );
                        return (
                          <tr
                            key={p.instructor_id ?? p.name}
                            className={tier === "none" ? "" : band(p.adj_rating)}
                          >
                            <td>{p.instructor_id != null ? (
                              <a href={`/professors/${p.instructor_id}`} className="underline underline-offset-2">{p.name ?? "View professor"}</a>
                            ) : p.name}</td>
                            <td className={forClass ? "" : "stat-overall"}>
                              {tier === "none" ? "—" : score(p.adj_rating)}
                            </td>
                            <td className={forClass ? "" : "stat-overall"}>
                              {tier === "none" ? "—" : score(p.adj_difficulty)}
                            </td>
                            <td>{pct(p.pct_a)}</td>
                            <td
                              title={
                                tier === "none"
                                  ? "Nobody has rated this professor, here or anywhere"
                                  : forClass
                                    ? `${p.class_reviews} review${p.class_reviews === 1 ? "" : "s"} of this class`
                                    : `No reviews of this class. ${p.professor_reviews} review${p.professor_reviews === 1 ? "" : "s"} of this professor overall, which is what these numbers are.`
                              }
                            >
                              {tier === "none"
                                ? "none"
                                : forClass
                                  ? `${p.class_reviews} here`
                                  : `${p.professor_reviews} all`}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
              {active.prereq_text ? (
                <div className="syllabus-note">
                  <Info size={17} />
                  <span>
                    <b>Prerequisites</b>
                    <small>{active.prereq_text}</small>
                  </span>
                </div>
              ) : null}
              <button
                className="add-plan"
                disabled={saving}
                onClick={() => toggle(active.code)}
              >
                {added.includes(active.code) ? (
                  <>
                    <Check size={16} />{" "}
                    {student ? "Saved to your plan" : "Added to plan"}
                  </>
                ) : (
                  <>
                    <Plus size={16} /> Add to my plan
                  </>
                )}
              </button>
              {!student ? (
                <small className="prof-none">
                  Sign in to keep your plan between visits.
                </small>
              ) : null}
              {courseError && <p role="alert">{courseError}</p>}
            </aside>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function SavedSchedules({
  onNav, schedules, error, busy, onOpen, student, dark, setDark,
}: {
  onNav: (p: "home" | "planner" | "explore" | "saved") => void;
  schedules: SavedSchedule[];
  error: string | null;
  busy: boolean;
  onOpen: (record: SavedSchedule, snapshot: Plan) => void;
  student: Student | null;
  dark: boolean;
  setDark: (value: boolean) => void;
}) {
  return (
    <main className={`inner-page ${dark ? "site-dark" : "site-light"}`}>
      <NavRail
        page="saved"
        onNav={onNav}
        student={student}
        dark={dark}
        setDark={setDark}
      />
      <section className="page-wrap">
        <div className="page-intro saved-intro">
          <h1>Your schedules</h1>
          <button onClick={() => onNav("planner")}>
            <Plus size={16} /> Build a new schedule
          </button>
        </div>
        {error && <p role="alert">{error}</p>}
        {!schedules.length && !error && <p>No saved schedules yet</p>}
        <div className="saved-grid">
          {schedules.map((record) => {
            const snapshot = readSavedPlan(record.payload);
            const label = record.label || snapshot?.name || "Saved schedule";
            if (!snapshot) return (
              <article key={record.id}>
                <h2>{label}</h2>
                <p>{record.term}</p>
                <p>This saved schedule cannot be displayed.</p>
              </article>
            );
            return (
              <article key={record.id} role="button" tabIndex={busy ? -1 : 0}
                aria-disabled={busy}
                aria-label={`Open ${label}`}
                onClick={() => { if (!busy) onOpen(record, snapshot); }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    if (!busy) onOpen(record, snapshot);
                  }
                }}>
                <header><span>{record.term}</span><Heart size={17} fill="currentColor" /></header>
                <h2>{label}</h2>
                <p>{snapshot.tags.join(" · ")}</p>
                <Mini courses={snapshot.courses} />
                <div className="saved-stats">
                  <span><Star size={14} /><b>{snapshot.rating}</b> rating</span>
                  <span><GraduationCap size={14} /><b>{snapshot.aRate}</b> A rate</span>
                  <span><Clock3 size={14} /><b>{snapshot.gap}</b> gap</span>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
function Metric({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div>
      {icon}
      <span>
        <small>{label}</small>
        <b>{value}</b>
      </span>
    </div>
  );
}
function Landing({
  onStart,
  onSaved,
  dark,
  setDark,
  catalog,
  student,
  savedCourses,
  savedWants,
  onBuild,
  serviceError,
}: {
  onStart: () => void;
  onSaved: () => void;
  dark: boolean;
  setDark: (v: boolean) => void;
  catalog: ExploreCourse[];
  student: Student | null;
  savedCourses: string[];
  savedWants: string;
  onBuild: (courses: string[], wants: string) => Promise<void>;
  serviceError?: string | null;
}) {
  const showcase = useMemo(() => showcaseCourses(catalog), [catalog]);
  const showcaseCredits = showcaseCreditTotal(showcase);

  const [courses, setCourses] = useState<string[]>(savedCourses),
    [entry, setEntry] = useState(""),
    [pref, setPref] = useState(savedWants),
    [analyzing, setAnalyzing] = useState(false),
    [picker, setPicker] = useState(false);
  const add = () => {
    const v = normalizeCourseCodes([entry])[0];
    if (v && !courses.includes(v)) setCourses([...courses, v]);
    setEntry("");
  };
  const go = async () => {
    if (!courses.length || analyzing) return;
    setAnalyzing(true);
    try {
      await onBuild(courses, pref);
    } finally {
      setAnalyzing(false);
    }
    onStart();
  };
  return (
    <main className={`minimal-home ${dark ? "dark-mode" : "light-mode"}`}>
      <NavRail
        page="home"
        onNav={(p) =>
          p === "saved" ? onSaved() : p === "home" ? undefined : onStart()
        }
        student={student}
        dark={dark}
        setDark={setDark}
      />
      {analyzing && (
        <div className="analysis-overlay">
          <div className="analysis-orbit">
            <Sparkles size={22} />
            <i />
            <i />
            <i />
          </div>
          <span>Building your best week</span>
          <h2>Comparing every possible schedule…</h2>
          <p>
            Comparing available sections, meeting times, professor ratings, and
            your preferences.
          </p>
          <div className="analysis-progress">
            <i />
          </div>
        </div>
      )}
      <CoursePicker
        open={picker}
        catalog={catalog}
        already={courses}
        onClose={() => setPicker(false)}
        onAdd={(codes) => setCourses([...new Set([...courses, ...codes])])}
      />
      <section className="minimal-stage">
        <div
          className="composer"
          aria-label="Several possible schedules becoming one optimized weekly schedule"
        >
          <div className="maroon-aura">
            <i />
            <i />
            <i />
          </div>
          <div className="gradient-ribbon">
            <span />
            <span />
            <span />
          </div>
          <div className="schedule-ghost ghost-left">
            <span />
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="schedule-ghost ghost-right">
            <span />
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="schedule-card">
            <header>
              <span>
                <Sparkles size={12} /> SAMPLE WEEK
              </span>
              <b>Illustration</b>
            </header>
            <div className="week-head">
              {days.map((d) => (
                <span key={d}>{d.slice(0, 3)}</span>
              ))}
            </div>
            <div className="week-grid">
              <i />
              <i />
              <i />
              <i />
              <i />
              {showcase.map((c, i) => (
                <span className={`block b${i + 1}`} key={c.code}>
                  <b>{c.label}</b>
                  <small>{SHOWCASE_TIMES[i % SHOWCASE_TIMES.length]}</small>
                </span>
              ))}
            </div>
            <footer>
              <span>
                <Star size={12} />
                Compare professors
              </span>
              <span>
                <Footprints size={12} />
                Plan class gaps
              </span>
              <span>
                <CalendarDays size={12} />
                Choose your days
              </span>
            </footer>
            <div className="scan-line" />
          </div>
          <div className="choice-chip chip-one">
            <Check size={11} /> Choose your hours
          </div>
          <div className="choice-chip chip-two">
            <Check size={11} /> Set your priorities
          </div>
        </div>
        <div className="minimal-copy">
          <h1>Let’s make your schedule.</h1>
          <p>
            Add your classes and tell us what a good week looks like to you.
          </p>
        </div>
        <div className="prompt-box">
          {serviceError && <p role="alert">{serviceError}</p>}
          <div className="course-input">
            <span className="course-icon">
              <SearchIcon size={18} duration={1.15} color="currentColor" />
            </span>
            <div className="course-chips">
              {courses.map((c) => (
                <button
                  key={c}
                  onClick={() => setCourses(courses.filter((x) => x !== c))}
                >
                  {c}
                  <X size={11} />
                </button>
              ))}
              <input
                value={entry}
                onChange={(e) => setEntry(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") add();
                }}
                placeholder={
                  courses.length
                    ? "Add another course…"
                    : `Try ${showcase[0]?.label ?? "a course code"}…`
                }
              />
            </div>
            <button
              className="add-course"
              onClick={() => setPicker(true)}
              aria-label="Browse courses"
            >
              <PlusIcon size={20} duration={1} color="currentColor" />
            </button>
          </div>
          <div className="preference-input">
            <Sparkles size={17} />
            <input
              value={pref}
              onChange={(e) => setPref(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") go();
              }}
              placeholder="Tell us your preferences — no Fridays, late mornings, best professors…"
            />
            <button onClick={go} disabled={!courses.length || analyzing}>
              {analyzing ? "Analyzing…" : "Continue"}{" "}
              {!analyzing && <ArrowRight size={16} />}
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

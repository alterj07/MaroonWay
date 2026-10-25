"use client";
// The planner UI. Data comes from the backend via src/app/page.tsx, which
// fetches real schedules and maps them into Plan/Course.
import { useMemo, useState } from "react";

import { DEFAULT_PRIORITIES } from "@/lib/plans";
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
const days = ["MON", "TUE", "WED", "THU", "FRI"],
  hours = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17];
const time = (n: number) => {
  const h = Math.floor(n),
    m = Math.round((n - h) * 60);
  return `${h > 12 ? h - 12 : h}:${String(m).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"}`;
};
function Mini({ courses }: { courses: Course[] }) {
  return (
    <div className="mini">
      <i />
      {days.map((d, i) => (
        <b key={d} style={{ gridColumn: i + 2 }}>
          {d[0]}
        </b>
      ))}
      {courses.flatMap((c, i) =>
        c.days.map((d) => (
          <span
            key={`${i}-${d}`}
            className={c.color}
            style={{
              gridColumn: d + 2,
              gridRow: Math.min(5, Math.floor((c.start - 8) / 2) + 2),
            }}
            title={`${c.code} · ${c.prof}`}
          >
            {c.code}
          </span>
        )),
      )}
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
  const missing = reason.match(/no sections on record for ([A-Z]+ ?\d+[A-Z]?)/i);
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
  const hour = h > 12 ? h - 12 : h;
  return `${hour} ${h >= 12 ? "PM" : "AM"}`;
}

/**
 * What is behind a block, on hover or keyboard focus.
 *
 * A block is a choice of instructor as much as a time, so the numbers that
 * justify the choice -- the rating, how hard it marks, how many A's it gives --
 * belong where the choice is rather than a page away.
 */
function CourseHover({ course }: { course: Course }) {
  const stat = (v: number | null | undefined, digits = 2) =>
    v === null || v === undefined ? "—" : Number(v).toFixed(digits);
  const share = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${Math.round(Number(v) * 100)}%`;

  return (
    <div className="hover-card" role="tooltip">
      <b>
        {course.code}
        {course.section ? <em>sec {course.section}</em> : null}
      </b>
      <span className="hover-prof">{course.prof}</span>
      <dl>
        <div>
          <dt>RMP rating</dt>
          <dd className={band(course.rating ?? null)}>
            {stat(course.rating)} / 5
          </dd>
        </div>
        <div>
          <dt>Difficulty</dt>
          <dd>{stat(course.difficulty)} / 5</dd>
        </div>
        <div>
          <dt>A rate</dt>
          <dd>{share(course.pctA)}</dd>
        </div>
        <div>
          <dt>Avg GPA</dt>
          <dd>{stat(course.gpa)}</dd>
        </div>
      </dl>
      <footer>
        <span>
          <Clock3 size={11} />
          {time(course.start)}–{time(course.end)}
        </span>
        <span>
          <MapPin size={11} />
          {course.room}
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

function Calendar({ plan }: { plan: Plan }) {
  return (
    <div className="cal-scroll">
      <div className="cal">
        <i />
        {days.map((d, i) => (
          <header
            key={d}
            className={i === 4 ? "off" : ""}
            style={{ gridColumn: i + 2 }}
          >
            <small>{d}</small>
            <b>{26 + i}</b>
          </header>
        ))}
        {hours.map((h) => (
          <label key={h} style={{ gridRow: h - 6 }}>
            {hourLabel(h)}
          </label>
        ))}
        {days.map((_, d) => (
          <div
            key={d}
            className={`lane ${d === 4 ? "off" : ""}`}
            style={{ gridColumn: d + 2 }}
          />
        ))}
        {plan.courses.flatMap((c) =>
          c.days.map((d) => {
            const hours = c.end - c.start;
            return (
              <article
                key={`${c.code}-${d}`}
                className={`${c.color} block`}
                tabIndex={0}
                style={{
                  // Measured off the same custom properties the grid uses, so
                  // changing either cannot leave the blocks beside their
                  // column again -- the offset used to hardcode a gutter width
                  // that the grid had since outgrown.
                  left: `calc(var(--cal-gutter) + ((100% - var(--cal-gutter)) / 5) * ${d})`,
                  width: "calc((100% - var(--cal-gutter)) / 5)",
                  top: `calc(var(--cal-head) + ${c.start - 8} * var(--cal-row))`,
                  height: `calc(${hours} * var(--cal-row))`,
                }}
              >
                <strong>{c.code}</strong>
                {/* A 50-minute class is one row tall; three lines do not fit in
                    it, and clipped text reads as a rendering fault. The hover
                    card carries the rest. */}
                {hours >= 1 ? (
                  <span>
                    {time(c.start)}–{time(c.end)}
                  </span>
                ) : null}
                {hours >= 1.5 ? (
                  <small>
                    <MapPin size={10} />
                    {c.room}
                  </small>
                ) : null}
                <CourseHover course={c} />
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
  terms,
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
  onBuildPlans: (codes: string[], wants: string) => Promise<Plan[]>;
  /** Terms with sections loaded, for the semester picker. */
  terms: string[];
  /** Persists a built schedule; what "Use this schedule" means. */
  onUseSchedule: (
    term: string,
    label: string,
    plan: Plan,
  ) => Promise<{ saved: boolean }>;
}) {
  const [plans, setPlans] = useState<Plan[]>(initialPlans);
  // A failure arrives as one marked plan, not as a list of schedules.
  const failed = plans.length === 1 && Boolean(plans[0].failed);
  // What the student actually asked for, so the builder's sidebar lists their
  // courses rather than the ones in the landing illustration.
  const [chosen, setChosen] = useState<string[]>(savedCourses);
  const build = async (codes: string[], wants: string) => {
    setChosen(codes);
    setPlans(await onBuildPlans(codes, wants));
  };
  // The sidebar shows the student's own courses; the showcase is only a
  // stand-in for a first visit when nothing has been chosen yet.
  const sidebar = useMemo(() => {
    if (!chosen.length) return showcaseCourses(courses);
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
    [saved, setSaved] = useState(false),
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
        : DEFAULT_PRIORITIES,
    ),
    // Each of these backs a control that previously did nothing.
    [term, setTerm] = useState(terms[0] ?? ""),
    [addingCourse, setAddingCourse] = useState(false),
    // The course a student has asked to remove, pending confirmation.
    [confirmDrop, setConfirmDrop] = useState<string | null>(null),
    [addingPriority, setAddingPriority] = useState(false),
    [priorityDraft, setPriorityDraft] = useState(""),
    [comparing, setComparing] = useState(false),
    [analysing, setAnalysing] = useState(false),
    [busy, setBusy] = useState(false),
    [kept, setKept] = useState(false);

  /** Everything the student has asked for, as one sentence for the decider. */
  const wants = priorities.filter(Boolean).join(", ");

  // Schedules built from the same instructors score identically on every
  // preference about teaching, so three equal badges are correct and
  // unhelpful. Say what does separate them instead of leaving it a mystery.
  const tied =
    plans.length > 1 && plans.every((p) => p.score === plans[0].score);

  async function rebuild(codes = chosen, text = wants) {
    if (!codes.length || busy) return;
    setBusy(true);
    setKept(false);
    try {
      await build(codes, text);
    } finally {
      setBusy(false);
    }
  }

  async function addCourses(codes: string[]) {
    setAddingCourse(false);
    const next = [...new Set([...chosen, ...codes])];
    if (next.length === chosen.length) return;
    await onSaveCourses(next, term || null);
    await rebuild(next);
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
    await onSaveCourses(next, term || null);
    if (next.length) await rebuild(next);
  }
  const plan = useMemo(
    () => plans.find((p) => p.id === active) ?? plans[0],
    [active, plans],
  );
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
        savedCourses={savedCourses}
        savedWants={savedWants}
        onBuild={build}
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
        savedCourses={savedCourses}
        onSaveCourses={onSaveCourses}
      />
    );
  if (page === "saved")
    return (
      <SavedSchedules
        onNav={setPage}
        plans={plans}
        onOpen={(id) => {
          setActive(id);
          setPage("planner");
        }}
        dark={dark}
        setDark={setDark}
        student={student}
      />
    );
  return (
    <main className={`app-page ${dark ? "site-dark" : "site-light"}`}>
      <AppHeader
        page="planner"
        onNav={setPage}
        dark={dark}
        setDark={setDark}
        student={student}
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
          <label className="term">
            <span>
              <CalendarDays size={17} />
              <i>
                <small>SEMESTER</small>
                <b>{term || "No term loaded"}</b>
              </i>
            </span>
            <ChevronDown size={16} />
            {/* A real select over the terms that have sections. This was a
                fixed string, so it could name a term the database had never
                heard of. */}
            <select
              aria-label="Semester"
              value={term}
              disabled={!terms.length}
              onChange={(e) => {
                setTerm(e.target.value);
                void onSaveCourses(chosen, e.target.value);
                void rebuild();
              }}
            >
              {terms.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <div className="label">
            <b>COURSES · {sidebarCredits} CREDITS</b>
            <button onClick={() => setAddingCourse((v) => !v)}>
              <Plus size={13} /> Add
            </button>
          </div>
          {confirmDrop ? (
            <div className="confirm-backdrop" onClick={() => setConfirmDrop(null)}>
              <div
                className="confirm"
                role="alertdialog"
                aria-modal="true"
                onClick={(e) => e.stopPropagation()}
              >
                <b>Remove {confirmDrop.replace(/^([A-Z]+)(\d.*)$/, "$1 $2")}?</b>
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
          {sidebar.map((c, i) => (
            <div className="course" key={c.code}>
              <i className={SHOWCASE_COLORS[i % SHOWCASE_COLORS.length]} />
              <span>
                <b>{c.label}</b>
                <small>{c.title ?? "Untitled"}</small>
              </span>
              <button
                className="course-drop"
                aria-label={`Remove ${c.label}`}
                onClick={() => setConfirmDrop(c.code)}
              >
                <X size={13} />
              </button>
            </div>
          ))}
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
            {priorities.map((p, i) => (
              <button
                onClick={() =>
                  setPriorities((v) => v.filter((_, x) => x !== i))
                }
                key={p}
              >
                <Check size={12} />
                {p}
                <X size={11} />
              </button>
            ))}
          </div>
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
            {(failed ? [] : plans).map((p, i) => (
              <button
                key={p.id}
                onClick={() => setActive(p.id)}
                className={active === p.id ? "selected" : ""}
              >
                <div>
                  <strong>
                    {i === 0 ? <Sparkles size={14} /> : "#" + (i + 1)}
                  </strong>
                  <em>{p.score}% match</em>
                </div>
                <h3>{p.name}</h3>
                <p>
                  {tied && p.idle !== undefined
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
                    onClick={() => setActive(p.id)}
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
                <button className="save" onClick={() => setSaved(!saved)}>
                  <Heart size={17} fill={saved ? "currentColor" : "none"} />
                </button>
                <button
                  className="use"
                  disabled={busy || kept || !term}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const result = await onUseSchedule(term, plan.name, plan);
                      setKept(result.saved);
                      if (result.saved) setPage("saved");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {kept ? "Saved" : "Use this schedule"}{" "}
                  <ArrowRight size={15} />
                </button>
              </div>
            </div>
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
                          {c.days.map((d) => DAY_LETTERS[d]).join("")}{" "}
                          {time(c.start)}–{time(c.end)}
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

function AppHeader({
  page,
  onNav,
  student,
  dark = true,
  setDark,
}: {
  page: string;
  onNav: (p: "home" | "planner" | "explore" | "saved") => void;
  dark?: boolean;
  setDark?: (v: boolean) => void;
  student?: Student | null;
}) {
  return (
    <header className="top">
      <button className="brand nav-brand" onClick={() => onNav("home")}>
        <span>
          <CalendarDays size={20} />
        </span>
        <b>MaroonWay</b>
      </button>
      <nav>
        <button
          className={page === "planner" ? "active" : ""}
          onClick={() => onNav("planner")}
        >
          Schedule builder
        </button>
        <button
          className={page === "explore" ? "active" : ""}
          onClick={() => onNav("explore")}
        >
          Course explorer
        </button>
        <button
          className={page === "saved" ? "active" : ""}
          onClick={() => onNav("saved")}
        >
          Saved schedules
        </button>
      </nav>
      <div className="account">
        <button
          onClick={() => setDark?.(!dark)}
          aria-label={`Switch to ${dark ? "light" : "dark"} mode`}
        >
          {dark ? <Sun size={17} /> : <Moon size={17} />}
        </button>
        <Account student={student} />
      </div>
    </header>
  );
}

/** Rating bands, so a card shows at a glance who is worth taking. */
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
const DAY_LETTERS = ["M", "T", "W", "R", "F"];

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
  onSaveCourses: (
    codes: string[],
    term?: string | null,
  ) => Promise<{ saved: boolean }>;
}) {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<ExploreCourse | null>(
    courses[0] ?? null,
  );
  const [added, setAdded] = useState<string[]>(savedCourses);
  const [saving, setSaving] = useState(false);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return courses;
    const compact = needle.replace(/\s+/g, "");
    return courses.filter(
      (c) =>
        c.code.toLowerCase().includes(compact) ||
        (c.title ?? "").toLowerCase().includes(needle) ||
        c.professors.some((p) => (p.name ?? "").toLowerCase().includes(needle)),
    );
  }, [q, courses]);

  const active =
    selected && shown.some((c) => c.code === selected.code)
      ? selected
      : (shown[0] ?? null);

  async function toggle(code: string) {
    const next = added.includes(code)
      ? added.filter((x) => x !== code)
      : [...added, code];
    setAdded(next);
    if (!student) return; // nothing to save to
    setSaving(true);
    try {
      await onSaveCourses(next);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="inner-page">
      <AppHeader
        page="explore"
        onNav={onNav}
        dark={dark}
        setDark={setDark}
        student={student}
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
              <div className="insight-grid">
                <Metric
                  icon={<Star />}
                  label="AVG. PROFESSOR"
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
                        <th>Department</th>
                        <th>Rating</th>
                        <th>Difficulty</th>
                        <th>A rate</th>
                        <th>Reviews</th>
                      </tr>
                    </thead>
                    <tbody>
                      {active.professors.map((p) => (
                        <tr
                          key={p.instructor_id ?? p.name}
                          className={band(p.adj_rating)}
                        >
                          <td>{p.name}</td>
                          <td className="prof-dept">{p.department ?? "—"}</td>
                          <td>{score(p.adj_rating)}</td>
                          <td>{score(p.adj_difficulty)}</td>
                          <td>{pct(p.pct_a)}</td>
                          <td>
                            {p.class_reviews > 0
                              ? `${p.class_reviews} for this class`
                              : `${p.professor_reviews} overall`}
                          </td>
                        </tr>
                      ))}
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
            </aside>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function SavedSchedules({
  onNav,
  plans,
  onOpen,
  student,
  dark,
  setDark,
}: {
  onNav: (p: "home" | "planner" | "explore" | "saved") => void;
  plans: Plan[];
  onOpen: (id: number) => void;
  student: Student | null;
  dark: boolean;
  setDark: (value: boolean) => void;
}) {
  const [favorites, setFavorites] = useState([1, 2]);
  return (
    <main className={`inner-page ${dark ? "site-dark" : "site-light"}`}>
      <AppHeader
        page="saved"
        onNav={onNav}
        dark={dark}
        setDark={setDark}
        student={student}
      />
      <section className="page-wrap">
        <div className="page-intro saved-intro">
          <h1>Your schedules</h1>
          <button onClick={() => onNav("planner")}>
            <Plus size={16} /> Build a new schedule
          </button>
        </div>
        <div className="saved-grid">
          {plans.map((p, i) => (
            <article
              key={p.id}
              role="button"
              tabIndex={0}
              aria-label={`Open ${p.name}`}
              onClick={() => onOpen(p.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") onOpen(p.id);
              }}
              className={favorites.includes(p.id) ? "favorite" : ""}
            >
              <header>
                <span>{`OPTION ${i + 1}`}</span>
                <button
                  aria-label={
                    favorites.includes(p.id)
                      ? "Remove favorite"
                      : "Save favorite"
                  }
                  onClick={(e) => {
                    e.stopPropagation();
                    setFavorites((v) =>
                      v.includes(p.id)
                        ? v.filter((x) => x !== p.id)
                        : [...v, p.id],
                    );
                  }}
                >
                  <Heart
                    size={17}
                    fill={favorites.includes(p.id) ? "currentColor" : "none"}
                  />
                </button>
              </header>
              <h2>{p.name}</h2>
              <p>{p.tags.join(" · ")}</p>
              <Mini courses={p.courses} />
              <div className="saved-stats">
                <span>
                  <Star size={14} />
                  <b>{p.rating}</b> rating
                </span>
                <span>
                  <GraduationCap size={14} />
                  <b>{p.aRate}</b> A rate
                </span>
                <span>
                  <Clock3 size={14} />
                  <b>{p.gap}</b> gap
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
function Range({
  icon,
  title,
  sub,
  width,
}: {
  icon: React.ReactNode;
  title: string;
  sub: string;
  width: string;
}) {
  return (
    <div className="range">
      <span>
        {icon}
        <i>
          <b>{title}</b>
          <small>{sub}</small>
        </i>
      </span>
      <div>
        <i style={{ width }} />
        <b style={{ left: width }} />
      </div>
    </div>
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
}) {
  const showcase = useMemo(() => showcaseCourses(catalog), [catalog]);
  const showcaseCredits = showcaseCreditTotal(showcase);

  const [courses, setCourses] = useState<string[]>(savedCourses),
    [entry, setEntry] = useState(""),
    [pref, setPref] = useState(savedWants),
    [analyzing, setAnalyzing] = useState(false),
    [picker, setPicker] = useState(false);
  const add = () => {
    const v = entry.trim().toUpperCase();
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
      <header className="minimal-nav">
        <a className="minimal-brand">
          <span>
            <CalendarDays size={18} />
          </span>
          <b>MaroonWay</b>
        </a>
        <div>
          <span>Made for Aggies</span>
          <button
            className="theme-toggle"
            onClick={() => setDark(!dark)}
            aria-label={`Switch to ${dark ? "light" : "dark"} mode`}
          >
            {dark ? <Sun size={15} /> : <Moon size={15} />}
            <i>{dark ? "Light" : "Dark"}</i>
          </button>
          <button onClick={onSaved}>My schedules</button>
          <Account student={student} />
        </div>
      </header>
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
            Checking professors, grade distributions, exam weight, syllabi, and
            walking time.
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
                <Sparkles size={12} /> YOUR BEST FIT
              </span>
              <b>94% match</b>
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
                <b>4.6</b> professors
              </span>
              <span>
                <Footprints size={12} />
                <b>9 min</b> walk
              </span>
              <span>
                <CalendarDays size={12} />
                <b>Fri</b> free
              </span>
            </footer>
            <div className="scan-line" />
          </div>
          <div className="choice-chip chip-one">
            <Check size={11} /> No 8 AMs
          </div>
          <div className="choice-chip chip-two">
            <Check size={11} /> Friday free
          </div>
        </div>
        <div className="minimal-copy">
          <h1>Let’s make your schedule.</h1>
          <p>
            Add your classes and tell us what a good week looks like to you.
          </p>
        </div>
        <div className="prompt-box">
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

"use client";
// The planner UI. Data comes from the backend via src/app/page.tsx, which
// fetches real schedules and maps them into Plan/Course.
import { useMemo, useState } from "react";
import { PlusIcon, SearchIcon } from "@animateicons/react/lucide";
import {
  ArrowRight,
  BookOpen,
  Bot,
  Building2,
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
          >
            {c.code.split(" ")[0]}
          </span>
        )),
      )}
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
            {time(h)}
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
          c.days.map((d) => (
            <article
              key={`${c.code}-${d}`}
              className={c.color}
              style={{
                left: `calc(48px + ((100% - 48px) / 5) * ${d})`,
                width: "calc((100% - 48px) / 5)",
                top: `${44 + (c.start - 8) * 25}px`,
                height: `${Math.max((c.end - c.start) * 25, 35)}px`,
              }}
            >
              <strong>{c.code}</strong>
              <span>
                {time(c.start)}–{time(c.end)}
              </span>
              <small>
                <MapPin size={10} />
                {c.room}
              </small>
            </article>
          )),
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
}) {
  const [plans, setPlans] = useState<Plan[]>(initialPlans);
  const build = async (codes: string[], wants: string) => {
    setPlans(await onBuildPlans(codes, wants));
  };
  const showcase = useMemo(() => showcaseCourses(courses), [courses]);
  const showcaseCredits = showcaseCreditTotal(showcase);
  const [page, setPage] = useState<"home" | "planner" | "explore" | "saved">(
      "home",
    ),
    [dark, setDark] = useState(true),
    [active, setActive] = useState(1),
    [saved, setSaved] = useState(false),
    [chat, setChat] = useState(true),
    [step, setStep] = useState(0),
    [priorities, setPriorities] = useState([
      "No classes before 9 AM",
      "Avoid Friday classes",
    ]);
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
            <button>Reset</button>
          </div>
          <button className="term">
            <span>
              <CalendarDays size={17} />
              <i>
                <small>SEMESTER</small>
                <b>Spring 2027</b>
              </i>
            </span>
            <ChevronDown size={16} />
          </button>
          <div className="label">
            <b>COURSES · {showcaseCredits} CREDITS</b>
            <button>
              <Plus size={13} /> Add
            </button>
          </div>
          {showcase.map((c, i) => (
            <div className="course" key={c.code}>
              <i className={SHOWCASE_COLORS[i % SHOWCASE_COLORS.length]} />
              <span>
                <b>{c.label}</b>
                <small>{c.title ?? "Untitled"}</small>
              </span>
              <X size={13} />
            </div>
          ))}
          <div className="label priority-label">
            <b>PRIORITIES</b>
            <button>
              <Plus size={13} /> Add
            </button>
          </div>
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
          <Range
            icon={<Clock3 />}
            title="Workload balance"
            sub="Prefer steady weeks"
            width="61%"
          />
          <Range
            icon={<Footprints />}
            title="Walking tolerance"
            sub="Up to 12 minutes"
            width="45%"
          />
          <button className="rebuild">
            <Sparkles size={15} /> Rebuild my schedule
          </button>
        </aside>
        <section className="results">
          <div className="result-title">
            <span>
              <small>TOP RECOMMENDATIONS</small>
              <h2>3 schedules built for you</h2>
            </span>
            <button>
              <SlidersHorizontal size={14} /> Compare
            </button>
          </div>
          <div className="cards">
            {plans.map((p, i) => (
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
                <p>{p.subtitle}</p>
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
          <div className="detail">
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
                <button className="use">
                  Use this schedule <ArrowRight size={15} />
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
                <p>
                  Strong professor ratings, no Friday classes, and a steady
                  workload with enough time between demanding courses.
                </p>
              </div>
              <button>
                View full analysis <ArrowRight size={13} />
              </button>
            </div>
          </div>
        </section>
      </div>
      <footer className="sources">
        <b>DATA SOURCES</b>
        <span>
          <Star /> Rate My Professors
        </span>
        <span>
          <Building2 /> Aggie Schedule Builder
        </span>
        <span>
          <BookOpen /> Course syllabi
        </span>
        <button>
          <Info /> How scoring works
        </button>
      </footer>
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
function band(rating: number | null) {
  if (rating === null) return "prof-unrated";
  if (rating >= 4.2) return "prof-great";
  if (rating >= 3.6) return "prof-good";
  if (rating >= 3.0) return "prof-mixed";
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
const SHOWCASE_COLORS = ["berry", "blue", "gold", "green"];
const SHOWCASE_TIMES = ["9:35", "9:35", "11:30", "12:45", "14:20"];

const CAMPUS_NAMES: Record<string, string> = {
  CSTAT: "College Station",
  GALV: "Galveston",
  QATAR: "Qatar",
  BLINN: "Blinn",
};

const pct = (v: number | null) =>
  v === null ? "—" : `${Math.round(v * 100)}%`;
const score = (v: number | null) => (v === null ? "—" : v.toFixed(2));

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
    [picker, setPicker] = useState(false),
    [pickQuery, setPickQuery] = useState(""),
    [picked, setPicked] = useState<string[]>([]);
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
  const addPicked = () => {
    setCourses([...new Set([...courses, ...picked])]);
    setPicked([]);
    setPicker(false);
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
      {picker && (
        <div className="picker-backdrop" onClick={() => setPicker(false)}>
          <section
            className="course-picker"
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <div>
                <span>ADD COURSES</span>
                <h2>What are you taking?</h2>
              </div>
              <button onClick={() => setPicker(false)}>
                <X size={18} />
              </button>
            </header>
            <div className="picker-search">
              <SearchIcon size={17} duration={1.15} color="currentColor" />
              <input
                autoFocus
                value={pickQuery}
                onChange={(e) => setPickQuery(e.target.value)}
                placeholder="Search course code or name…"
              />
            </div>
            <div className="picker-results">
              {catalog
                .filter((c) =>
                  (c.code + " " + (c.title ?? ""))
                    .toLowerCase()
                    .includes(pickQuery.toLowerCase()),
                )
                .slice(0, 80)
                .map((c) => (
                  <button
                    key={c.code}
                    className={
                      picked.includes(c.code) || courses.includes(c.code)
                        ? "picked"
                        : ""
                    }
                    disabled={courses.includes(c.code)}
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
                      {courses.includes(c.code) ? (
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
              <button disabled={!picked.length} onClick={addPicked}>
                Add {picked.length || ""} course{picked.length === 1 ? "" : "s"}
              </button>
            </footer>
          </section>
        </div>
      )}
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

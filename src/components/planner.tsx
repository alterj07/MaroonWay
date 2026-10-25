"use client";
// The planner UI. Data comes from the backend via src/app/page.tsx, which
// fetches real schedules and maps them into Plan/Course.
import { useMemo, useState } from "react";
import { SearchIcon, SquarePlusIcon } from "@animateicons/react/lucide";
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
      {days.map((d) => (
        <b key={d}>{d[0]}</b>
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
          <header key={d} className={i === 4 ? "off" : ""}>
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
export function Planner({ plans }: { plans: Plan[] }) {
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
      />
    );
  if (page === "explore")
    return <Explorer onNav={setPage} dark={dark} setDark={setDark} />;
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
      />
    );
  return (
    <main className={`app-page ${dark ? "site-dark" : "site-light"}`}>
      <AppHeader page="planner" onNav={setPage} dark={dark} setDark={setDark} />
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
            <b>COURSES · 14 CREDITS</b>
            <button>
              <Plus size={13} /> Add
            </button>
          </div>
          {[
            ["MATH 152", "Engineering Math II", "berry"],
            ["PHYS 206", "Newtonian Mechanics", "blue"],
            ["ENGR 102", "Engineering Lab I", "gold"],
            ["CHEM 107/117", "General Chemistry", "green"],
          ].map((c) => (
            <div className="course" key={c[0]}>
              <i className={c[2]} />
              <span>
                <b>{c[0]}</b>
                <small>{c[1]}</small>
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
function AppHeader({
  page,
  onNav,
  dark = true,
  setDark,
}: {
  page: string;
  onNav: (p: "home" | "planner" | "explore" | "saved") => void;
  dark?: boolean;
  setDark?: (v: boolean) => void;
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
        <span>JK</span>
        <div>
          <b>Joshua</b>
          <small>Engineering ’30</small>
        </div>
        <ChevronDown size={15} />
      </div>
    </header>
  );
}
const catalog = [
  {
    code: "MATH 152",
    name: "Engineering Mathematics II",
    credits: 4,
    prof: "Amy Austin",
    rating: 4.8,
    a: 62,
    exams: 55,
    room: "BLOC",
    tags: ["Popular", "Honors available"],
  },
  {
    code: "PHYS 206",
    name: "Newtonian Mechanics",
    credits: 3,
    prof: "Tatiana Erukhimova",
    rating: 4.7,
    a: 54,
    exams: 60,
    room: "MPHY",
    tags: ["Great lectures"],
  },
  {
    code: "ENGR 102",
    name: "Engineering Lab I",
    credits: 2,
    prof: "Jennifer Warren",
    rating: 4.5,
    a: 71,
    exams: 25,
    room: "ZACH",
    tags: ["Project-based"],
  },
  {
    code: "CHEM 107",
    name: "General Chemistry",
    credits: 3,
    prof: "Donald Collins",
    rating: 4.3,
    a: 49,
    exams: 68,
    room: "HELD",
    tags: ["Exam-heavy"],
  },
  {
    code: "CSCE 120",
    name: "Program Design & Concepts",
    credits: 4,
    prof: "John Keyser",
    rating: 4.6,
    a: 57,
    exams: 40,
    room: "PETR",
    tags: ["Coding", "High workload"],
  },
];
function Explorer({
  onNav,
  dark,
  setDark,
}: {
  onNav: (p: "home" | "planner" | "explore" | "saved") => void;
  dark: boolean;
  setDark: (value: boolean) => void;
}) {
  const [q, setQ] = useState(""),
    [selected, setSelected] = useState(catalog[0]),
    [added, setAdded] = useState<string[]>([]);
  const shown = catalog.filter((c) =>
    (c.code + " " + c.name + " " + c.prof)
      .toLowerCase()
      .includes(q.toLowerCase()),
  );
  return (
    <main className={`inner-page ${dark ? "site-dark" : "site-light"}`}>
      <AppHeader page="explore" onNav={onNav} dark={dark} setDark={setDark} />
      <section className="page-wrap explorer-wrap">
        <div className="explore-search">
          <SearchIcon size={18} duration={1.15} color="currentColor" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by course, professor, or keyword…"
          />
          <button>
            <SlidersHorizontal size={15} /> Filters
          </button>
        </div>
        <div className="explore-layout">
          <div className="course-list">
            {shown.map((c) => (
              <button
                className={selected.code === c.code ? "selected" : ""}
                key={c.code}
                onClick={() => setSelected(c)}
              >
                <span>
                  <b>{c.code}</b>
                  <small>{c.name}</small>
                </span>
                <div>
                  <em>
                    <Star size={12} />
                    {c.rating}
                  </em>
                  <strong>{c.credits} credits</strong>
                  <ArrowRight size={15} />
                </div>
              </button>
            ))}
          </div>
          <aside className="course-detail">
            <div className="detail-code">
              <span>{selected.code}</span>
              <em>{selected.credits} CREDITS</em>
            </div>
            <h2>{selected.name}</h2>
            <p>
              <b>{selected.prof}</b> · {selected.room}
            </p>
            <div className="insight-grid">
              <Metric
                icon={<Star />}
                label="PROFESSOR"
                value={`${selected.rating} / 5`}
              />
              <Metric
                icon={<GraduationCap />}
                label="A RATE"
                value={`${selected.a}%`}
              />
              <Metric
                icon={<BookOpen />}
                label="EXAM WEIGHT"
                value={`${selected.exams}%`}
              />
            </div>
            <div className="tag-row">
              {selected.tags.map((t) => (
                <span key={t}>{t}</span>
              ))}
            </div>
            <div className="syllabus-note">
              <Sparkles size={17} />
              <span>
                <b>AI syllabus summary</b>
                <small>
                  Weekly assignments,{" "}
                  {selected.exams >= 60
                    ? "exam-heavy grading"
                    : "balanced grading"}
                  , and consistent attendance expectations.
                </small>
              </span>
            </div>
            <button
              className="add-plan"
              onClick={() =>
                setAdded((v) =>
                  v.includes(selected.code)
                    ? v.filter((x) => x !== selected.code)
                    : [...v, selected.code],
                )
              }
            >
              {added.includes(selected.code) ? (
                <>
                  <Check size={16} /> Added to plan
                </>
              ) : (
                <>
                  <Plus size={16} /> Add to my plan
                </>
              )}
            </button>
          </aside>
        </div>
      </section>
    </main>
  );
}
function SavedSchedules({
  onNav,
  plans,
  onOpen,
  dark,
  setDark,
}: {
  onNav: (p: "home" | "planner" | "explore" | "saved") => void;
  plans: Plan[];
  onOpen: (id: number) => void;
  dark: boolean;
  setDark: (value: boolean) => void;
}) {
  const [favorites, setFavorites] = useState([1, 2]);
  return (
    <main className={`inner-page ${dark ? "site-dark" : "site-light"}`}>
      <AppHeader page="saved" onNav={onNav} dark={dark} setDark={setDark} />
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
}: {
  onStart: () => void;
  onSaved: () => void;
  dark: boolean;
  setDark: (v: boolean) => void;
}) {
  const [courses, setCourses] = useState(["MATH 152", "PHYS 206"]),
    [entry, setEntry] = useState(""),
    [pref, setPref] = useState(""),
    [analyzing, setAnalyzing] = useState(false),
    [picker, setPicker] = useState(false),
    [pickQuery, setPickQuery] = useState(""),
    [picked, setPicked] = useState<string[]>([]);
  const add = () => {
    const v = entry.trim().toUpperCase();
    if (v && !courses.includes(v)) setCourses([...courses, v]);
    setEntry("");
  };
  const go = () => {
    if (!courses.length || analyzing) return;
    setAnalyzing(true);
    setTimeout(onStart, 1900);
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
                  (c.code + c.name)
                    .toLowerCase()
                    .includes(pickQuery.toLowerCase()),
                )
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
                        {c.name} · {c.credits} credits
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
              <span className="block b1">
                <b>MATH 152</b>
                <small>9:35</small>
              </span>
              <span className="block b2">
                <b>PHYS 206</b>
                <small>9:35</small>
              </span>
              <span className="block b3">
                <b>ENGR 102</b>
                <small>11:30</small>
              </span>
              <span className="block b4">
                <b>CHEM 107</b>
                <small>12:45</small>
              </span>
              <span className="block b5">
                <b>CHEM 117</b>
                <small>2:15</small>
              </span>
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
                  courses.length ? "Add another course…" : "Try MATH 152…"
                }
              />
            </div>
            <button
              className="add-course"
              onClick={() => setPicker(true)}
              aria-label="Browse courses"
            >
              <SquarePlusIcon size={20} duration={1} color="currentColor" />
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
        <div className="quick-prefs">
          <span>Try:</span>
          {[
            "No 8 AMs",
            "Free Fridays",
            "Shortest walks",
            "Highest-rated professors",
          ].map((p) => (
            <button key={p} onClick={() => setPref(p)}>
              {p}
            </button>
          ))}
        </div>
      </section>
      <footer className="minimal-footer">
        <span>
          <i /> Live TAMU course data
        </span>
        <small>Ratings · Grade distributions · Syllabi · Walking time</small>
        <b>Built in Aggieland ♥</b>
      </footer>
    </main>
  );
}

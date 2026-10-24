import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, Fingerprint } from "lucide-react";
import { DAEMON } from "./api";

const SPRING = { type: "spring", stiffness: 260, damping: 28 } as const;

type Phase =
  | "intro" | "transcribe" | "freetype" | "targets" | "drag"
  | "scroll" | "form" | "done";

const PHASES: Phase[] = [
  "intro", "transcribe", "freetype", "targets", "drag", "scroll", "form", "done",
];

type Progress = { keystrokes?: number; pointer_samples?: number; clicks?: number };

export default function Enroll() {
  const [phase, setPhase] = useState<Phase>("intro");
  const [sentences, setSentences] = useState<string[]>([]);
  const [progress, setProgress] = useState<Progress>({});
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [profile, setProfile] = useState("user");
  const [name, setName] = useState("");

  useEffect(() => {
    const id = setInterval(() => {
      fetch(`${DAEMON}/enroll/progress`).then((r) => r.json())
        .then(setProgress).catch(() => {});
    }, 2000);
    return () => clearInterval(id);
  }, []);

  const start = async () => {
    const role = profile === "user" ? "user" : "impostor";
    const r = await fetch(`${DAEMON}/enroll/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profile, display_name: name, role }),
    });
    const j = await r.json();
    setSentences(j.sentences);
    setPhase("transcribe");
  };

  const finish = async () => {
    const r = await fetch(`${DAEMON}/enroll/finish`, { method: "POST" });
    setResult(await r.json());
    setPhase("done");
  };

  const idx = PHASES.indexOf(phase);
  const frac = idx / (PHASES.length - 1);

  return (
    <div className="min-h-screen flex flex-col">
      {/* progress along the top */}
      <div className="fixed top-0 left-0 right-0 h-[3px] bg-[rgba(255,255,255,0.06)] z-50">
        <motion.div
          className="h-full bg-[var(--blue)]"
          animate={{ width: `${frac * 100}%` }}
          transition={SPRING}
        />
      </div>

      <header className="flex items-center justify-between px-10 py-6">
        <div className="flex items-center gap-3">
          <Fingerprint size={20} strokeWidth={1.5} />
          <span className="font-semibold tracking-tight">Gait · Enrollment</span>
        </div>
        <div className="label">
          {progress.keystrokes ?? 0} keystrokes · {progress.pointer_samples ?? 0}{" "}
          pointer samples
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={phase}
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -24 }}
            transition={SPRING}
            className="w-full max-w-3xl"
          >
            {phase === "intro" && (
              <Intro profile={profile} setProfile={setProfile}
                name={name} setName={setName} onStart={start} />
            )}
            {phase === "transcribe" && (
              <Transcribe sentences={sentences} onDone={() => setPhase("freetype")} />
            )}
            {phase === "freetype" && (
              <FreeType onDone={() => setPhase("targets")} />
            )}
            {phase === "targets" && <Targets onDone={() => setPhase("drag")} />}
            {phase === "drag" && <DragTask onDone={() => setPhase("scroll")} />}
            {phase === "scroll" && <ScrollTask onDone={() => setPhase("form")} />}
            {phase === "form" && <FormTask onDone={finish} />}
            {phase === "done" && <Done result={result} />}
          </motion.div>
        </AnimatePresence>
      </main>

      <footer className="text-center py-5 label">
        We store timing features only — never keys, text, or screen contents.
      </footer>
    </div>
  );
}

function Btn({ children, onClick, disabled }: {
  children: React.ReactNode; onClick?: () => void; disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="bg-[var(--blue)] text-white rounded-full px-7 py-2.5 text-[16px]
        font-medium disabled:opacity-30 hover:brightness-110 transition"
    >
      {children}
    </button>
  );
}

function Intro(p: {
  profile: string; setProfile: (v: string) => void;
  name: string; setName: (v: string) => void; onStart: () => void;
}) {
  return (
    <div className="text-center">
      <h1 className="text-[56px] font-semibold tracking-tight leading-tight">
        Five minutes.<br />Then your Mac knows it’s you.
      </h1>
      <p className="text-[var(--label)] text-[19px] mt-4 max-w-xl mx-auto">
        Type a few sentences, click a few targets. Gait learns your rhythm —
        not your words.
      </p>
      <div className="flex items-center justify-center gap-3 mt-10">
        {["user", "impostor_1", "impostor_2", "impostor_3"].map((id) => (
          <button
            key={id}
            onClick={() => p.setProfile(id)}
            className={`px-5 py-2 rounded-full border text-[15px] transition ${
              p.profile === id
                ? "border-[var(--blue)] text-[var(--blue)]"
                : "border-[var(--border)] text-[var(--label)]"
            }`}
          >
            {id === "user" ? "Presenter (user)" : id.replace("_", " ")}
          </button>
        ))}
      </div>
      <input
        value={p.name}
        onChange={(e) => p.setName(e.target.value)}
        placeholder="Display name"
        className="mt-6 bg-[var(--surface)] border border-[var(--border)] rounded-2xl
          px-5 py-3 text-center outline-none focus:border-[var(--blue)] w-72"
      />
      <div className="mt-8">
        <Btn onClick={p.onStart}>Begin</Btn>
      </div>
    </div>
  );
}

function Transcribe({ sentences, onDone }: {
  sentences: string[]; onDone: () => void;
}) {
  const [i, setI] = useState(0);
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { ref.current?.focus(); }, [i]);

  const next = () => {
    setText("");
    if (i + 1 >= sentences.length) onDone();
    else setI(i + 1);
  };

  return (
    <div className="text-center">
      <div className="label mb-6">Transcribe · {i + 1} of {sentences.length}</div>
      <div className="text-[32px] font-medium tracking-tight leading-snug mb-8">
        {sentences[i]}
      </div>
      <textarea
        ref={ref}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); if (text.length > 8) next(); }
        }}
        rows={2}
        placeholder="Type it here, press Return when done (typos are fine)"
        className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-2xl
          px-6 py-4 text-[19px] outline-none focus:border-[var(--blue)] resize-none"
      />
    </div>
  );
}

function FreeType({ onDone }: { onDone: () => void }) {
  const [left, setLeft] = useState(60);
  const [text, setText] = useState("");
  useEffect(() => {
    const id = setInterval(() => setLeft((l) => l - 1), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => { if (left <= 0) onDone(); }, [left, onDone]);
  return (
    <div className="text-center">
      <div className="label mb-4">Free typing · {Math.max(left, 0)}s</div>
      <div className="text-[28px] font-medium tracking-tight mb-6">
        Describe your morning in detail.
      </div>
      <textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-2xl
          px-6 py-4 text-[18px] outline-none focus:border-[var(--blue)] resize-none"
        placeholder="This text is never stored — only your rhythm."
      />
    </div>
  );
}

function Targets({ onDone }: { onDone: () => void }) {
  const TOTAL = 20;
  const [n, setN] = useState(0);
  const target = useMemo(() => ({
    x: 8 + Math.random() * 84,
    y: 15 + Math.random() * 65,
    r: 18 + Math.random() * 30,
  }), [n]);

  const hit = useCallback(() => {
    if (n + 1 >= TOTAL) onDone();
    else setN(n + 1);
  }, [n, onDone]);

  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute top-20 left-0 right-0 text-center pointer-events-none">
        <div className="label">Click the circles · {n + 1} of {TOTAL}</div>
      </div>
      <motion.button
        key={n}
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={SPRING}
        onClick={hit}
        className="absolute rounded-full"
        style={{
          left: `${target.x}%`, top: `${target.y}%`,
          width: target.r * 2, height: target.r * 2,
          background: "radial-gradient(circle, rgba(10,132,255,0.9), rgba(10,132,255,0.5))",
          boxShadow: "0 0 24px rgba(10,132,255,0.5)",
        }}
      />
    </div>
  );
}

function DragTask({ onDone }: { onDone: () => void }) {
  const TOTAL = 6;
  const [n, setN] = useState(0);
  const [pos, slot] = useMemo(() => {
    return [
      { x: 10 + Math.random() * 30, y: 30 + Math.random() * 40 },
      { x: 60 + Math.random() * 30, y: 30 + Math.random() * 40 },
    ];
  }, [n]);
  const dragging = useRef(false);
  const elRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current || !elRef.current) return;
      elRef.current.style.left = `${e.clientX - 28}px`;
      elRef.current.style.top = `${e.clientY - 28}px`;
    };
    const onUp = (e: MouseEvent) => {
      if (!dragging.current) return;
      dragging.current = false;
      const sx = (slot.x / 100) * window.innerWidth;
      const sy = (slot.y / 100) * window.innerHeight;
      if (Math.hypot(e.clientX - sx, e.clientY - sy) < 60) {
        if (n + 1 >= TOTAL) onDone();
        else setN(n + 1);
      } else if (elRef.current) {
        elRef.current.style.left = `${(pos.x / 100) * window.innerWidth}px`;
        elRef.current.style.top = `${(pos.y / 100) * window.innerHeight}px`;
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [n, pos, slot, onDone]);

  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute top-20 left-0 right-0 text-center pointer-events-none">
        <div className="label">Drag the square into the ring · {n + 1} of {TOTAL}</div>
      </div>
      <div
        className="absolute rounded-full border-2 border-dashed border-[var(--amber)]"
        style={{
          left: `calc(${slot.x}% - 40px)`, top: `calc(${slot.y}% - 40px)`,
          width: 80, height: 80, opacity: 0.8,
        }}
      />
      <div
        ref={elRef}
        key={n}
        onMouseDown={() => { dragging.current = true; }}
        className="absolute rounded-xl cursor-grab active:cursor-grabbing"
        style={{
          left: `${(pos.x / 100) * window.innerWidth}px`,
          top: `${(pos.y / 100) * window.innerHeight}px`,
          width: 56, height: 56, background: "var(--blue)",
          boxShadow: "0 8px 24px rgba(10,132,255,0.4)",
        }}
      />
    </div>
  );
}

function ScrollTask({ onDone }: { onDone: () => void }) {
  const TOTAL = 5;
  const [round, setRound] = useState(0);
  const targetLine = useMemo(() => 8 + Math.floor(Math.random() * 30), [round]);
  const boxRef = useRef<HTMLDivElement>(null);

  const clickLine = (i: number) => {
    if (i !== targetLine) return;
    if (round + 1 >= TOTAL) onDone();
    else {
      setRound(round + 1);
      boxRef.current?.scrollTo({ top: 0 });
    }
  };

  return (
    <div>
      <div className="label text-center mb-4">
        Scroll to the highlighted line and click it · {round + 1} of {TOTAL}
      </div>
      <div
        ref={boxRef}
        className="card h-[55vh] overflow-y-auto px-8 py-6 feed"
      >
        {Array.from({ length: 40 }, (_, i) => (
          <div
            key={i}
            onClick={() => clickLine(i)}
            className={`py-2 border-b border-[var(--border)] text-[16px] cursor-pointer ${
              i === targetLine
                ? "text-[var(--amber)] font-semibold"
                : "text-[var(--label)]"
            }`}
          >
            {i === targetLine ? "→ Click this line" : `Line ${i + 1} — nothing to see here.`}
          </div>
        ))}
      </div>
    </div>
  );
}

function FormTask({ onDone }: { onDone: () => void }) {
  const fields = ["First name", "City", "Favorite food", "A color", "An animal", "A number"];
  const [vals, setVals] = useState<string[]>(Array(6).fill(""));
  const complete = vals.every((v) => v.length >= 2);
  return (
    <div>
      <div className="label text-center mb-6">
        One last form — contents are discarded
      </div>
      <div className="grid grid-cols-2 gap-4">
        {fields.map((f, i) => (
          <input
            key={f}
            value={vals[i]}
            onChange={(e) =>
              setVals(vals.map((v, j) => (j === i ? e.target.value : v)))}
            placeholder={f}
            className="bg-[var(--surface)] border border-[var(--border)] rounded-2xl
              px-5 py-3 outline-none focus:border-[var(--blue)]"
          />
        ))}
      </div>
      <div className="text-center mt-8">
        <Btn onClick={onDone} disabled={!complete}>Finish enrollment</Btn>
      </div>
    </div>
  );
}

function Done({ result }: { result: Record<string, unknown> | null }) {
  return (
    <div className="text-center">
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={SPRING}
        className="mx-auto w-20 h-20 rounded-full flex items-center justify-center"
        style={{ background: "rgba(48,209,88,0.15)", border: "1px solid var(--green)" }}
      >
        <Check size={36} className="text-[var(--green)]" />
      </motion.div>
      <h2 className="text-[40px] font-semibold tracking-tight mt-6">Enrolled.</h2>
      <p className="text-[var(--label)] text-[17px] mt-2">
        {result ? (
          <>
            {String(result.windows)} feature windows saved
            {result.training === "started" && " · model training started"}
          </>
        ) : "Session saved."}
      </p>
      <div className="mt-8">
        <a href="#/" className="text-[var(--blue)] text-[17px]">
          Open the dashboard →
        </a>
      </div>
    </div>
  );
}

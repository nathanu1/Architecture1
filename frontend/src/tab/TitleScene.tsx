import { motion, useReducedMotion } from "motion/react";

// The start screen's artwork, drawn in code: a pastel town on rolling hills, the wordmark as a
// chunky sticker, and the town's three residents. Everything here is decoration (aria-hidden);
// the page's real heading and controls live in Gate.tsx.

const INK = "#2a2838";

function House({ x, y, w = 170, h = 108, body, roof, roofEdge }: { x: number; y: number; w?: number; h?: number; body: string; roof: string; roofEdge: string }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect x={w * 0.64} y={-h - 58} width={24} height={50} rx={5} fill={roofEdge} />
      <path d={`M-16 ${-h + 4} L${w / 2} ${-h - 74} L${w + 16} ${-h + 4} Z`} fill={roof} stroke={roofEdge} strokeWidth={7} strokeLinejoin="round" />
      <rect x={0} y={-h} width={w} height={h} rx={12} fill={body} stroke="rgba(42,40,56,0.12)" strokeWidth={5} />
      <rect x={w * 0.13} y={-h + 24} width={36} height={36} rx={8} fill="#ffd166" stroke="#e8a93b" strokeWidth={5} />
      <rect x={w * 0.87 - 36} y={-h + 24} width={36} height={36} rx={8} fill="#ffd166" stroke="#e8a93b" strokeWidth={5} />
      <rect x={w / 2 - 18} y={-60} width={36} height={60} rx={9} fill="#9a6a4a" />
      <circle cx={w / 2 + 9} cy={-28} r={3.5} fill="#f6d27a" />
    </g>
  );
}

function Tree({ x, y, s = 1, dot = "#ffffff" }: { x: number; y: number; s?: number; dot?: string }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`}>
      <rect x={-8} y={-50} width={16} height={52} rx={6} fill="#9a6a4a" />
      <circle cx={0} cy={-88} r={46} fill="#5fb86a" />
      <circle cx={-14} cy={-102} r={22} fill="#7fcf86" opacity={0.75} />
      {[
        [-20, -76],
        [16, -98],
        [22, -70],
        [-4, -112],
      ].map(([cx, cy]) => (
        <circle key={`${cx}${cy}`} cx={cx} cy={cy} r={5} fill={dot} />
      ))}
    </g>
  );
}

function Cloud({ x, y, s = 1, drift, reduce }: { x: number; y: number; s?: number; drift: number; reduce: boolean | null }) {
  return (
    <motion.g animate={reduce ? undefined : { x: [0, drift, 0] }} transition={{ duration: 48, repeat: Infinity, ease: "easeInOut" }}>
      <g transform={`translate(${x} ${y}) scale(${s})`} fill="#ffffff" opacity={0.94}>
        <ellipse cx={0} cy={0} rx={70} ry={30} />
        <ellipse cx={-42} cy={8} rx={44} ry={24} />
        <ellipse cx={46} cy={10} rx={50} ry={24} />
        <ellipse cx={8} cy={-22} rx={40} ry={28} />
      </g>
    </motion.g>
  );
}

/** The town behind the menu: sky, sun, clouds, houses on hills and a path into town. */
export function TownBackdrop() {
  const reduce = useReducedMotion();
  return (
    <svg aria-hidden="true" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" className="pointer-events-none absolute inset-0 size-full dark:brightness-[0.62] dark:saturate-[0.85]">
      <circle cx={1190} cy={150} r={108} fill="#fff3c4" opacity={0.28} />
      <circle cx={1190} cy={150} r={72} fill="#fff3c4" />
      <Cloud x={250} y={150} s={1.25} drift={46} reduce={reduce} />
      <Cloud x={900} y={96} s={0.9} drift={-38} reduce={reduce} />
      <Cloud x={1330} y={330} s={0.8} drift={30} reduce={reduce} />
      <Cloud x={560} y={300} s={0.62} drift={-24} reduce={reduce} />

      <path d="M0 566 C220 470 430 500 660 540 S1120 462 1440 540 V900 H0Z" fill="#b9e6a4" />
      <House x={96} y={548} body="#f8c9da" roof="#e2725b" roofEdge="#b5503d" />
      <House x={352} y={532} w={150} h={96} body="#fff6e3" roof="#6c8fd6" roofEdge="#4f6fb3" />
      <House x={946} y={520} w={150} h={96} body="#d3c6f3" roof="#e2725b" roofEdge="#b5503d" />
      <House x={1178} y={536} body="#cdeedd" roof="#b77fb8" roofEdge="#93609a" />
      <Tree x={300} y={560} s={0.9} />
      <Tree x={548} y={556} s={0.66} dot="#f26d6d" />
      <Tree x={902} y={548} s={0.66} dot="#f26d6d" />
      <Tree x={1128} y={556} s={0.9} />
      <Tree x={1392} y={570} s={1.05} />
      <Tree x={40} y={584} s={1.05} dot="#f26d6d" />

      <path d="M0 640 C300 578 600 612 800 628 S1200 590 1440 640 V900 H0Z" fill="#9fd98e" />
      {/* a path from the square up into town */}
      <path d="M690 630 C664 720 560 800 430 900 H1010 C880 800 776 720 750 630 Z" fill="#f6ead2" />
      {[
        [712, 690, 18],
        [752, 744, 24],
        [660, 786, 26],
        [776, 830, 30],
        [600, 856, 30],
      ].map(([cx, cy, r]) => (
        <ellipse key={`${cx}${cy}`} cx={cx} cy={cy} rx={r} ry={r * 0.36} fill="none" stroke="#e3d3b3" strokeWidth={4} />
      ))}

      <path d="M0 772 C360 706 1080 706 1440 772 V900 H0Z" fill="#8bd27c" />
      {[
        [120, 820, "#ffffff"],
        [240, 866, "#ffd166"],
        [1180, 828, "#ffffff"],
        [1320, 872, "#f8c9da"],
        [1050, 880, "#ffd166"],
        [330, 800, "#f8c9da"],
      ].map(([cx, cy, fill]) => (
        <g key={`${cx}${cy}`} transform={`translate(${cx} ${cy})`}>
          <circle r={9} fill={fill as string} />
          <circle r={3.5} fill="#f2a33a" />
        </g>
      ))}
    </svg>
  );
}

/** "Hearthside" as a sticker: white letters, a thick outline and a soft drop, slightly tilted. */
export function Wordmark({ className = "" }: { className?: string }) {
  const text = { x: 400, y: 138, textAnchor: "middle" as const, fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 132, letterSpacing: 1 };
  return (
    <svg aria-hidden="true" viewBox="0 0 800 200" className={className} width={800} height={200}>
      <g transform="rotate(-3 400 100)">
        <text {...text} y={150} fill="#1b4f8f" stroke="#1b4f8f" strokeWidth={26} strokeLinejoin="round" opacity={0.26}>
          Hearthside
        </text>
        <text {...text} fill="#2f7fd1" stroke="#2f7fd1" strokeWidth={26} strokeLinejoin="round">
          Hearthside
        </text>
        <text {...text} fill="#ffffff" stroke="#ffffff" strokeWidth={4} strokeLinejoin="round">
          Hearthside
        </text>
      </g>
    </svg>
  );
}

interface Look {
  skin: string;
  hair: string;
  shirt: string;
  pants: string;
  style: "bun" | "long" | "short";
  extra?: "apron" | "headphones" | "glasses";
}

// the three neighbours of the town in a tab, in the colours the town itself gives them
const NEIGHBOURS: Look[] = [
  { skin: "#C98E6A", hair: "#2B1D1A", shirt: "#3BA7A0", pants: "#3D4A63", style: "long", extra: "headphones" },
  { skin: "#D9A57E", hair: "#3A2522", shirt: "#E8735F", pants: "#5B4B6B", style: "bun", extra: "apron" },
  { skin: "#F2CDB0", hair: "#E2C27A", shirt: "#7BAF6E", pants: "#4A5568", style: "short", extra: "glasses" },
];

function Neighbour({ look, delay, reduce, big = false }: { look: Look; delay: number; reduce: boolean | null; big?: boolean }) {
  return (
    <motion.svg
      viewBox="0 0 120 172"
      width={120}
      height={172}
      className={`h-full w-auto ${big ? "" : "mb-1 scale-[0.9]"}`}
      style={{ transformOrigin: "50% 100%" }}
      animate={reduce ? undefined : { y: [0, -5, 0] }}
      transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut", delay }}
    >
      <ellipse cx={60} cy={164} rx={34} ry={7} fill="rgba(42,40,56,0.14)" />
      {look.style === "long" ? <path d="M18 50 C18 20 102 20 102 50 V104 C102 118 90 122 84 112 H36 C30 122 18 118 18 104 Z" fill={look.hair} /> : null}
      <rect x={44} y={126} width={14} height={30} rx={6} fill={look.pants} />
      <rect x={62} y={126} width={14} height={30} rx={6} fill={look.pants} />
      <ellipse cx={50} cy={158} rx={11} ry={6} fill={INK} />
      <ellipse cx={70} cy={158} rx={11} ry={6} fill={INK} />
      <rect x={22} y={92} width={15} height={36} rx={7.5} fill={look.shirt} transform="rotate(10 30 92)" />
      <rect x={83} y={92} width={15} height={36} rx={7.5} fill={look.shirt} transform="rotate(-10 90 92)" />
      <circle cx={24} cy={128} r={7} fill={look.skin} />
      <circle cx={96} cy={128} r={7} fill={look.skin} />
      <rect x={34} y={86} width={52} height={50} rx={17} fill={look.shirt} />
      {look.extra === "apron" ? <rect x={42} y={100} width={36} height={36} rx={9} fill="#fff6e3" /> : null}
      {look.style === "bun" ? <circle cx={60} cy={8} r={14} fill={look.hair} /> : null}
      <circle cx={60} cy={52} r={41} fill={look.skin} />
      <path
        d={look.style === "short" ? "M19 50 C18 8 102 8 101 50 C96 38 88 32 80 36 C74 26 62 28 58 36 C50 28 38 30 34 38 C28 36 22 42 19 50Z" : "M19 54 C17 10 103 10 101 54 C93 38 78 32 60 35 C42 32 27 38 19 54Z"}
        fill={look.hair}
      />
      <ellipse cx={46} cy={58} rx={5} ry={7.5} fill={INK} />
      <ellipse cx={74} cy={58} rx={5} ry={7.5} fill={INK} />
      <circle cx={47.6} cy={55} r={2} fill="#ffffff" />
      <circle cx={75.6} cy={55} r={2} fill="#ffffff" />
      <circle cx={34} cy={70} r={6.5} fill="#f08a7b" opacity={0.45} />
      <circle cx={86} cy={70} r={6.5} fill="#f08a7b" opacity={0.45} />
      <path d="M50 72 Q60 81 70 72" fill="none" stroke={INK} strokeWidth={3.2} strokeLinecap="round" />
      {look.extra === "glasses" ? (
        <g fill="none" stroke={INK} strokeWidth={3}>
          <circle cx={46} cy={58} r={11} />
          <circle cx={74} cy={58} r={11} />
          <path d="M57 58 H63" />
        </g>
      ) : null}
      {look.extra === "headphones" ? (
        <g>
          <path d="M20 52 C20 0 100 0 100 52" fill="none" stroke="#f2792b" strokeWidth={6} strokeLinecap="round" />
          <rect x={12} y={44} width={14} height={26} rx={7} fill="#f2792b" />
          <rect x={94} y={44} width={14} height={26} rx={7} fill="#f2792b" />
        </g>
      ) : null}
    </motion.svg>
  );
}

/** The three neighbours, standing together; the middle one a step forward. */
export function Neighbours({ className = "" }: { className?: string }) {
  const reduce = useReducedMotion();
  return (
    <div aria-hidden="true" className={`flex items-end justify-center gap-1 ${className}`}>
      <Neighbour look={NEIGHBOURS[0]} delay={0.5} reduce={reduce} />
      <Neighbour look={NEIGHBOURS[1]} delay={0} reduce={reduce} big />
      <Neighbour look={NEIGHBOURS[2]} delay={1} reduce={reduce} />
    </div>
  );
}

import CrystalizedBall from "./CrystalizedBall";
import type { CrystalizedBallProps } from "./CrystalizedBall";
import type { AssistantState } from "../api";

type OrbLook = Pick<
  CrystalizedBallProps,
  | "preset"
  | "color"
  | "speed"
  | "crackle"
  | "flares"
  | "glow"
  | "sparks"
  | "particleCount"
  | "fill"
  | "motion"
  | "haze"
  | "dustSpeed"
  | "size"
>;

const LOOK: Record<AssistantState, OrbLook> = {
  idle: {
    preset: "frost",
    color: "#5C9BB8",
    speed: 0.55,
    crackle: 0.3,
    flares: 0.25,
    glow: 0.55,
    sparks: 0.25,
    particleCount: 9000,
    fill: 0.4,
    motion: "drift",
    haze: 0.55,
    dustSpeed: 0.6,
    size: 0.72,
  },
  listening: {
    preset: "aurora",
    color: "#4DB8E8",
    speed: 1.15,
    crackle: 0.75,
    flares: 0.55,
    glow: 0.85,
    sparks: 0.55,
    particleCount: 14000,
    fill: 0.55,
    motion: "rise",
    haze: 0.7,
    dustSpeed: 1.1,
    size: 0.78,
  },
  thinking: {
    preset: "plasma",
    color: "#E8A24A",
    speed: 1.35,
    crackle: 0.9,
    flares: 0.7,
    glow: 0.95,
    sparks: 0.65,
    particleCount: 16000,
    fill: 0.6,
    motion: "orbit",
    haze: 0.75,
    dustSpeed: 1.25,
    size: 0.8,
  },
  speaking: {
    preset: "solar",
    color: "#3DCEA7",
    speed: 1.55,
    crackle: 0.7,
    flares: 0.8,
    glow: 1,
    sparks: 0.75,
    particleCount: 15000,
    fill: 0.58,
    motion: "rise",
    haze: 0.65,
    dustSpeed: 1.4,
    size: 0.82,
  },
  needs_approval: {
    preset: "ember",
    color: "#F08A3A",
    speed: 0.95,
    crackle: 0.85,
    flares: 0.6,
    glow: 0.9,
    sparks: 0.7,
    particleCount: 12000,
    fill: 0.5,
    motion: "orbit",
    haze: 0.6,
    dustSpeed: 0.9,
    size: 0.76,
  },
  error: {
    preset: "eclipse",
    color: "#E06B6B",
    speed: 1.8,
    crackle: 1,
    flares: 0.9,
    glow: 0.8,
    sparks: 0.85,
    particleCount: 11000,
    fill: 0.45,
    motion: "fall",
    haze: 0.5,
    dustSpeed: 1.5,
    size: 0.74,
  },
};

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

/** Scale Crystalized Ball energy from TTS audio_level while speaking. */
function withSpeakEnergy(look: OrbLook, level: number): OrbLook {
  const a = clamp01(level);
  if (a <= 0.02) return look;
  const boost = 0.35 + a * 0.9;
  return {
    ...look,
    speed: (look.speed ?? 1) * (0.9 + a * 1.25),
    crackle: Math.min(1, (look.crackle ?? 0.5) * boost),
    flares: Math.min(1.2, (look.flares ?? 0.5) * boost),
    glow: Math.min(1.2, (look.glow ?? 0.6) * (0.9 + a * 0.45)),
    sparks: Math.min(1, (look.sparks ?? 0.5) * boost),
    dustSpeed: (look.dustSpeed ?? 1) * (1 + a * 1.8),
    fill: Math.min(0.85, (look.fill ?? 0.5) * (1 + a * 0.12)),
    size: Math.min(0.95, (look.size ?? 0.75) * (1 + a * 0.1)),
    motion: a > 0.4 ? "rise" : look.motion,
  };
}

export type AmyOrbProps = {
  state: AssistantState;
  audioLevel?: number;
  className?: string;
  compact?: boolean;
  interactive?: boolean;
};

export default function AmyOrb({
  state,
  audioLevel = 0,
  className = "",
  compact = false,
  interactive = true,
}: AmyOrbProps) {
  const base = LOOK[state] ?? LOOK.idle;
  const speakLevel =
    state === "speaking" ? (audioLevel > 0.05 ? audioLevel : 0.55) : 0;
  const look = speakLevel > 0 ? withSpeakEnergy(base, speakLevel) : base;
  return (
    <div
      className={`amy-orb ${compact ? "amy-orb--compact" : ""} ${className}`.trim()}
      data-state={state}
      data-level={audioLevel.toFixed(2)}
      aria-label={`Amy orb — ${state.replace("_", " ")}`}
    >
      <CrystalizedBall
        {...look}
        audioLevel={speakLevel}
        theme="dark"
        interactive={interactive}
        hoverStrength={0.65}
        intro={!compact}
        className="amy-orb__ball"
      />
    </div>
  );
}

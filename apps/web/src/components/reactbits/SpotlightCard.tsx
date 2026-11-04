import { CSSProperties, MouseEvent, ReactNode, useRef } from "react";
import "./SpotlightCard.css";

type Props = {
  children: ReactNode;
  className?: string;
  spotlightColor?: string;
};

/** React Bits–style spotlight card (pointer-follow glow). */
export default function SpotlightCard({
  children,
  className = "",
  spotlightColor = "rgba(77, 184, 232, 0.22)",
}: Props) {
  const ref = useRef<HTMLDivElement>(null);

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--spot-x", `${e.clientX - r.left}px`);
    el.style.setProperty("--spot-y", `${e.clientY - r.top}px`);
  };

  return (
    <div
      ref={ref}
      className={`rb-spotlight ${className}`.trim()}
      onMouseMove={onMove}
      style={{ "--spot-color": spotlightColor } as CSSProperties}
    >
      {children}
    </div>
  );
}

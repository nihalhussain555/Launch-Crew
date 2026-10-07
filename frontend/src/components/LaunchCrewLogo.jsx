import { useId } from "react";

/* Launch Crew brand mark: abstract "L" + orbit + rocket, cyan→blue→indigo→violet gradient.
   One source of truth for the logo everywhere (navbar, sidebar, auth, footer, favicon). */
export default function LaunchCrewLogo({ variant = "full", size = 26, className = "" }) {
  const raw = useId();
  const id = "lcg" + (raw.replace(/[^a-zA-Z0-9]/g, "") || "0");
  const mark = (
    <svg className="lc-mark" width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#06B6D4" />
          <stop offset="0.4" stopColor="#0891B2" />
          <stop offset="0.75" stopColor="#6366F1" />
          <stop offset="1" stopColor="#8B5CF6" />
        </linearGradient>
      </defs>
      <path d="M15 9 V25 H27" stroke={`url(#${id})`} strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <ellipse cx="20" cy="25" rx="13.5" ry="5" stroke={`url(#${id})`} strokeWidth="2.2" transform="rotate(-18 20 25)" />
      <g transform="translate(24.5 4.5) rotate(38)">
        <path d="M4 0c2.3 1.9 2.3 6.2 0 9-2.3-2.8-2.3-7.1 0-9z" fill={`url(#${id})`} />
        <path d="M2.3 6.6 0.4 9.6l2.6-.9M5.7 6.6l1.9 3-2.6-.9" fill={`url(#${id})`} />
      </g>
    </svg>
  );

  if (variant === "icon") return mark;
  return (
    <span className={`lc-logo ${variant} ${className}`} style={{ "--lc": `${size}px` }}>
      {mark}
      {variant !== "mark" && (
        <span className="lc-word">
          Launch <span className="lc-word-grad">Crew</span>
        </span>
      )}
    </span>
  );
}

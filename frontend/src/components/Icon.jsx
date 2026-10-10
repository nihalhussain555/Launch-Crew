/* Launch Crew custom line-icon set — hand-drawn SVG, 24px grid, stroke:currentColor.
   Not an emoji or a third-party icon font; single source of truth for chrome glyphs. */

const svg = (children, extra = {}) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={extra.strokeWidth ?? 1.7}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
    className={`ic ${extra.className || ""}`}
    width={extra.size || 20}
    height={extra.size || 20}
  >
    {children}
  </svg>
);

const PATHS = {
  home: (
    <>
      <path d="M4 11.2 12 4l8 7.2" />
      <path d="M6 10v9a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-9" />
      <path d="M10 20v-5h4v5" />
    </>
  ),
  folder: (
    <path d="M4 8a2 2 0 0 1 2-2h3.2l2 2H18a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
  ),
  sparkle: (
    <>
      <path d="M11 3.6 12.9 8l4.4 1.9-4.4 1.9L11 16.1 9.1 11.8 4.7 9.9 9.1 8z" />
      <path d="M17.5 14.4l.9 2 2 .9-2 .9-.9 2-.9-2-2-.9 2-.9z" />
    </>
  ),
  gear: (
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19.3 14.8a1.5 1.5 0 0 0 .3 1.66l.05.05a1.8 1.8 0 1 1-2.55 2.55l-.05-.05a1.5 1.5 0 0 0-1.66-.3 1.5 1.5 0 0 0-.9 1.37v.17a1.8 1.8 0 1 1-3.6 0v-.09a1.5 1.5 0 0 0-.98-1.37 1.5 1.5 0 0 0-1.66.3l-.05.05a1.8 1.8 0 1 1-2.55-2.55l.05-.05a1.5 1.5 0 0 0 .3-1.66 1.5 1.5 0 0 0-1.37-.9H4a1.8 1.8 0 1 1 0-3.6h.09A1.5 1.5 0 0 0 5.46 7.9a1.5 1.5 0 0 0-.3-1.66l-.05-.05A1.8 1.8 0 1 1 7.66 3.7l.05.05a1.5 1.5 0 0 0 1.66.3H9.5a1.5 1.5 0 0 0 .9-1.37V2.6a1.8 1.8 0 1 1 3.6 0v.09a1.5 1.5 0 0 0 .9 1.37 1.5 1.5 0 0 0 1.66-.3l.05-.05a1.8 1.8 0 1 1 2.55 2.55l-.05.05a1.5 1.5 0 0 0-.3 1.66v.06a1.5 1.5 0 0 0 1.37.9H20a1.8 1.8 0 1 1 0 3.6h-.09a1.5 1.5 0 0 0-1.37.9z" />
    </>
  ),
  monitor: (
    <>
      <rect x="3.2" y="4.4" width="17.6" height="11.5" rx="1.8" />
      <path d="M8.5 20h7M12 15.9V20" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="3.8" />
      <path d="M12 2.6v2.1M12 19.3v2.1M2.6 12h2.1M19.3 12h2.1M5.3 5.3l1.5 1.5M17.2 17.2l1.5 1.5M18.7 5.3l-1.5 1.5M6.8 17.2l-1.5 1.5" />
    </>
  ),
  moon: <path d="M20 14.6A8 8 0 1 1 9.4 4a6.5 6.5 0 0 0 10.6 10.6z" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="M20 20l-3.4-3.4" />
    </>
  ),
  rocket: (
    <>
      <path d="M12 3.2c2.7 1.8 4.1 4.9 4.1 7.8 0 1.8-.6 3.6-1.6 5.1H9.5a8.4 8.4 0 0 1-1.6-5.1c0-2.9 1.4-6 4.1-7.8z" />
      <circle cx="12" cy="10.2" r="1.5" />
      <path d="M9.4 16.1 7.2 19l.4-3.4M14.6 16.1 16.8 19l-.4-3.4" />
      <path d="M12 16.1v3" />
    </>
  ),
  deploy: (
    <>
      <path d="M12 3.4l2.1 1.4 2.5-.1.9 2.3 2 1.4-.6 2.5.6 2.5-2 1.4-.9 2.3-2.5-.1L12 19.3l-2.1-1.4-2.5.1-.9-2.3-2-1.4.6-2.5-.6-2.5 2-1.4.9-2.3 2.5.1z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4.2" />
      <circle cx="12" cy="12" r="0.8" fill="currentColor" />
    </>
  ),
  hash: <path d="M9 4.5 7.4 19.5M16.6 4.5 15 19.5M4.4 9h15M3.8 15h15" />,
  logout: (
    <>
      <path d="M12 4H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5" />
      <path d="M16 8.5 19.5 12 16 15.5M9.5 12h10" />
    </>
  ),
  left: <path d="M15 5l-7 7 7 7" />,
  refresh: (
    <>
      <path d="M20 12a8 8 0 1 1-2.3-5.6" />
      <path d="M20 4.2V8h-3.8" />
    </>
  ),
  link: (
    <>
      <path d="M10.5 13.5 13.5 10.5" />
      <path d="M12.3 8.2 14 6.5a3.4 3.4 0 0 1 4.8 4.8l-1.7 1.7M11.7 15.8 10 17.5a3.4 3.4 0 0 1-4.8-4.8l1.7-1.7" />
    </>
  ),
  arrowRight: <path d="M5 12h13M13 6l6 6-6 6" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  check: <path d="M5 12.5 10 17 19 7" />,
  plus: <path d="M12 5v14M5 12h14" />,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  eye: (
    <>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  eyeOff: (
    <>
      <path d="M4 4l16 16" />
      <path d="M9.6 6A9.9 9.9 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17.5 17.5 0 0 1-3.7 4.4M6.3 7.9A17 17 0 0 0 2.5 12S6 18.5 12 18.5a9.7 9.7 0 0 0 3.2-.5" />
      <path d="M9.9 10.1a3 3 0 0 0 4.1 4.2" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="9" rx="2" />
      <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5.5" width="18" height="13" rx="2.5" />
      <path d="m4.5 7.5 7.5 5.5 7.5-5.5" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8.5" r="3.6" />
      <path d="M5 20a7 7 0 0 1 14 0" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.4 2.4 2.4 14.6 0 17M12 3.5c-2.4 2.4-2.4 14.6 0 17" />
    </>
  ),
  cpu: (
    <>
      <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
      <path d="M10 6.5V4M14 6.5V4M10 20v-2.5M14 20v-2.5M6.5 10H4M6.5 14H4M20 10h-2.5M20 14h-2.5" />
    </>
  ),
  layers: (
    <>
      <path d="m12 4 8 4-8 4-8-4 8-4z" />
      <path d="m4 12.5 8 4 8-4M4 16.5 12 20l8-3.5" />
    </>
  ),
  chart: (
    <>
      <path d="M5 20V11M11 20V5M17 20v-6" />
      <path d="M3 20h18" />
    </>
  ),
  workflow: (
    <>
      <rect x="3.5" y="4" width="6" height="6" rx="1.5" />
      <rect x="14.5" y="14" width="6" height="6" rx="1.5" />
      <path d="M6.5 10v3.5A2.5 2.5 0 0 0 9 16h5.5" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3.5 5 6v5.5c0 4.3 3 7.3 7 8.5 4-1.2 7-4.2 7-8.5V6l-7-2.5z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  book: (
    <>
      <path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z" />
      <path d="M5 17.5A1.5 1.5 0 0 1 6.5 16H19" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.6 9.4a2.5 2.5 0 0 1 4.8.8c0 1.7-2.4 2-2.4 3.3" />
      <path d="M12 17h.01" />
    </>
  ),
  star: <path d="M12 3.7l2.55 5.17 5.7.83-4.12 4.02.97 5.68L12 16.87l-5.1 2.53.97-5.68L3.75 9.7l5.7-.83z" />,
  starFilled: (
    <path
      fill="currentColor"
      d="M12 3.7l2.55 5.17 5.7.83-4.12 4.02.97 5.68L12 16.87l-5.1 2.53.97-5.68L3.75 9.7l5.7-.83z"
    />
  ),
  alert: (
    <>
      <path d="M12 4.6 21 19.4H3z" />
      <path d="M12 10v4" />
      <path d="M12 16.6h.01" />
    </>
  ),
  audit: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.4 15.4 20 20" />
      <path d="m7.8 10.6 1.9 1.9 3.6-3.7" />
    </>
  ),
  chat: (
    <>
      <path d="M4 6.5A1.5 1.5 0 0 1 5.5 5h13A1.5 1.5 0 0 1 20 6.5v8A1.5 1.5 0 0 1 18.5 16H9l-5 3.2z" />
      <path d="M8 9h8M8 12h5" />
    </>
  ),
  code: (
    <>
      <path d="m8.5 8.5-4 3.5 4 3.5" />
      <path d="m15.5 8.5 4 3.5-4 3.5" />
      <path d="m13.4 5-2.8 14" />
    </>
  ),
  key: (
    <>
      <circle cx="8.2" cy="8.2" r="3.8" />
      <path d="m11 11 8 8" />
      <path d="m15.6 15.6-2 2M17.4 17.4l-2 2" />
    </>
  ),
};

export default function Icon({ name, size, strokeWidth, className = "" }) {
  const node = PATHS[name];
  if (!node) return null;
  return svg(node, { size, strokeWidth, className });
}

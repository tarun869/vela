/**
 * Original abstract stencil marks for the connector catalog.
 *
 * These are hand-drawn category glyphs (battery, solar, EV plug, thermostat,
 * smart panel, generator, grid/hub) — deliberately NOT the vendors' trademarked
 * logos and not letter monograms. They render in `currentColor` so they sit as
 * clean white stencils on the brand-coloured logo tile.
 */
import type { ReactNode } from 'react'

function Glyph({ children }: { children: ReactNode }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  )
}

const dot = (cx: number, cy: number, r = 1.4) => (
  <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} fill="currentColor" stroke="none" />
)

// Each entry returns the inner SVG geometry for one connector id.
const MARKS: Record<string, ReactNode> = {
  // Battery storage — lightning bolt
  tesla: (
    <path d="M13 2.5 6 13h5l-1.2 8.5L18 10h-5z" fill="currentColor" stroke="none" />
  ),
  // Solar (microinverters) — module array of cells
  enphase: (
    <>
      <rect x="4.5" y="4.5" width="6" height="6" rx="1.2" />
      <rect x="13.5" y="4.5" width="6" height="6" rx="1.2" />
      <rect x="4.5" y="13.5" width="6" height="6" rx="1.2" />
      <rect x="13.5" y="13.5" width="6" height="6" rx="1.2" />
    </>
  ),
  // Solar (panels + optimizer) — tilted panel on legs
  solaredge: (
    <>
      <rect x="4" y="6.5" width="16" height="9" rx="1" />
      <path d="M9.3 6.5v9M14.6 6.5v9M4 11h16" />
      <path d="M9 15.5 8 19M15 15.5l1 3.5" />
    </>
  ),
  // EV charging — connector nozzle + cable
  chargepoint: (
    <>
      <rect x="8.5" y="6.5" width="7" height="9.5" rx="2" />
      <path d="M10.5 6.5V4M13.5 6.5V4M12 16v2.5" />
      <path d="M12 18.5c3 0 3 2.5 0 2.5" />
    </>
  ),
  // Smart thermostat (round dial) — concentric ring
  nest: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      {dot(12, 12, 3.2)}
    </>
  ),
  // Market-access platform "Leap" — an upward leaping arc + arrowhead
  leap: (
    <>
      <path d="M4 18C9 18 9 6.5 19.5 6" />
      <path d="M14.8 5 19.8 6 19 11" />
      {dot(4, 18)}
    </>
  ),
  // Battery storage (sun) — radial sunburst
  sonnen: (
    <>
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.2 5.2l1.8 1.8M17 17l1.8 1.8M18.8 5.2 17 7M7 17l-1.8 1.8" />
    </>
  ),
  // Backup generator — engine block + rotor
  generac: (
    <>
      <path d="M9 6h6V4M9 6V4" />
      <rect x="4" y="6.5" width="16" height="9.5" rx="1.5" />
      <circle cx="12" cy="11.2" r="2.6" />
      <path d="M7 16v3M17 16v3" />
    </>
  ),
  // Smart thermostat (squircle) — rounded square + center
  ecobee: (
    <>
      <rect x="4.5" y="4.5" width="15" height="15" rx="5.5" />
      {dot(12, 12, 2.4)}
    </>
  ),
  // EV charging (wall unit) — charger box + coiled cable
  wallbox: (
    <>
      <rect x="5.5" y="3.5" width="8" height="11" rx="2" />
      {dot(9.5, 7, 1.3)}
      <path d="M13.5 11c3.2 0 3.2 3 0 3s-3.2 3 0 3" />
    </>
  ),
  // DERMS platform (grid) — mesh of nodes
  autogrid: (
    <>
      <path d="M6 6h12M6 12h12M6 18h12M6 6v12M12 6v12M18 6v12" opacity="0.5" />
      {[dot(6, 6), dot(12, 6), dot(18, 6), dot(6, 12), dot(12, 12), dot(18, 12), dot(6, 18), dot(12, 18), dot(18, 18)]}
    </>
  ),
  // Smart panel — breaker panel with switch rows
  span: (
    <>
      <rect x="5" y="3.5" width="14" height="17" rx="1.8" />
      <path d="M8 8h3.2M8 11.5h3.2M8 15h3.2M12.8 8H16M12.8 11.5H16M12.8 15H16" />
    </>
  ),
  // Battery storage (rising sun) — half-sun over horizon
  sunrun: (
    <>
      <path d="M3.5 18h17" />
      <path d="M7 18a5 5 0 0 1 10 0" />
      <path d="M12 7.5V5M5.7 10 4 8.7M18.3 10 20 8.7" />
    </>
  ),
  // Whole-home battery — house + bolt
  franklinwh: (
    <>
      <path d="M4.5 11 12 4.5 19.5 11" />
      <path d="M6.5 10v9.5h11V10" />
      <path d="M12.5 12 10.5 15h2l-0.6 3 3-4h-2z" fill="currentColor" stroke="none" />
    </>
  ),
}

// Generic fallback — a node on a network (any unmapped connector id).
const FALLBACK: ReactNode = (
  <>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 4v5M12 15v5M4 12h5M15 12h5" />
  </>
)

export function ConnectorMark({ id }: { id: string }) {
  return <Glyph>{MARKS[id] ?? FALLBACK}</Glyph>
}

export interface DispatchPoint {
  time: string
  bess: number    // kW, positive = discharge, negative = charge
  solar: number   // kW
  ev: number      // kW, charging load
  hvac: number    // kW, flex demand reduction
  lmp: number     // $/MWh
}

export interface PriceFanPoint {
  time: string
  p10: number
  p25: number
  p50: number
  p75: number
  p90: number
  actual?: number
}

function lmpAt(i: number): number {
  if (i < 12)  return 27 + Math.sin(i * 0.5) * 1.5
  if (i < 20)  return 29 + (i - 12) * 0.8
  if (i < 28)  return 35 + (i - 20) * 2.5
  if (i < 36)  return 55 + (i - 28) * 1.8
  if (i < 44)  return 68 + Math.sin((i - 36) * 0.7) * 5
  if (i < 50)  return 48 - (i - 44) * 3.5
  if (i < 56)  return 28 - (56 - i) * 3.5
  if (i < 64)  return 32 + (i - 56) * 3.8
  if (i < 72)  return 62 + (i - 64) * 5.5
  if (i < 78)  return 106 + (i - 72) * 2
  if (i < 86)  return 118 - (i - 78) * 7.5
  if (i < 92)  return 58 - (i - 86) * 3
  return 36 - (i - 92) * 0.5
}

function solarAt(i: number): number {
  if (i < 24 || i >= 72) return 0
  return Math.max(0, Math.round(16800 * Math.sin((Math.PI * (i - 24)) / 48)))
}

export function generateDispatchSeries(): DispatchPoint[] {
  return Array.from({ length: 48 }, (_, k) => {
    const i = k * 2
    const h = Math.floor(i / 4)
    const m = (i % 4) * 15
    const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
    const lmp = Math.round(lmpAt(i) * 10) / 10
    let bess = 0
    if (i >= 42 && i < 58) bess = -(11800 + (i - 42) * 100)
    else if (i >= 66 && i < 84) bess = 14200 - Math.abs(i - 75) * 250
    const solar = solarAt(i)
    const ev    = i < 24 || i >= 88 ? 4200 : 0
    const hvac  = i >= 66 && i < 82 ? 1300 : 0
    return { time, bess: Math.round(bess), solar, ev, hvac, lmp }
  })
}

export function generatePriceFan(): PriceFanPoint[] {
  return Array.from({ length: 48 }, (_, k) => {
    const i = k * 2
    const h = Math.floor(i / 4)
    const m = (i % 4) * 15
    const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '00')}`
    const p50 = lmpAt(i)
    const spread = 3 + Math.abs(p50 - 50) * 0.07
    return {
      time,
      p10:    Math.max(0, Math.round((p50 - spread * 2.2) * 10) / 10),
      p25:    Math.max(0, Math.round((p50 - spread) * 10) / 10),
      p50:    Math.round(p50 * 10) / 10,
      p75:    Math.round((p50 + spread) * 10) / 10,
      p90:    Math.round((p50 + spread * 2.2) * 10) / 10,
      actual: i < 76 ? Math.round((p50 + Math.sin(i * 1.3) * spread * 0.4) * 10) / 10 : undefined,
    }
  })
}

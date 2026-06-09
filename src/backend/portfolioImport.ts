// Client-side portfolio import: parse CSV / pasted asset lists into the
// ParsedAsset shape the analysis engine consumes, plus a few realistic sample
// portfolios for one-click demos. No dependencies — the demo works fully offline.

import type { Chemistry, DemoAssetType } from '../types/demo'
import type { ParsedAsset } from './onboardAnalysis'

export type ImportResult = {
  assets: ParsedAsset[]
  warnings: string[]
  detectedColumns: Record<string, string> // canonical field -> source header
  source: string
}

// ── Type & chemistry inference ──────────────────────────────────────────────────

function inferType(raw: string): { type: DemoAssetType; confidence: number } {
  const s = raw.toLowerCase()
  if (/bess|batter|storage|li-?ion|lfp|nmc|nca/.test(s)) return { type: 'BESS', confidence: 0.95 }
  if (/solar|pv|photovolta/.test(s)) return { type: 'Solar', confidence: 0.95 }
  if (/wind|turbine/.test(s)) return { type: 'Wind', confidence: 0.95 }
  if (/ev|charg|v2g|vehicle|depot/.test(s)) return { type: 'EV_Fleet', confidence: 0.88 }
  if (/flex|load|hvac|demand|dr |dr$|curtail|building|campus/.test(s)) return { type: 'Flex_Load', confidence: 0.82 }
  return { type: 'BESS', confidence: 0.55 }
}

function inferChemistry(raw: string): Chemistry | null {
  const s = raw.toUpperCase()
  if (s.includes('LFP') || s.includes('IRON')) return 'LFP'
  if (s.includes('NMC')) return 'NMC'
  if (s.includes('NCA')) return 'NCA'
  return null
}

const NUM = (v: string | undefined): number | null => {
  if (v == null) return null
  const m = v.replace(/[, ]/g, '').match(/-?\d+(\.\d+)?/)
  return m ? parseFloat(m[0]) : null
}

// ── Column detection ────────────────────────────────────────────────────────────

const COLUMN_ALIASES: Record<string, RegExp> = {
  asset_id: /^(asset|name|id|site|resource|project|facility)/i,
  asset_type: /^(type|class|technology|tech|resource.?type|category)/i,
  rated_mw: /(mw\b|power|rated.?mw|capacity.?mw|nameplate|kw\b)/i,
  rated_mwh: /(mwh|energy|duration|kwh|storage)/i,
  chemistry: /(chem|cell)/i,
  region: /(region|node|iso|rto|location|market|zone|pnode)/i,
  year: /(year|commission|cod|online|vintage)/i,
}

function splitLine(line: string, delim: string): string[] {
  // Minimal CSV: handles simple quoting.
  const out: string[] = []
  let cur = ''
  let q = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (c === '"') q = !q
    else if (c === delim && !q) {
      out.push(cur)
      cur = ''
    } else cur += c
  }
  out.push(cur)
  return out.map((s) => s.trim().replace(/^"|"$/g, ''))
}

function detectDelim(line: string): string {
  const counts: Array<[string, number]> = [
    [',', (line.match(/,/g) || []).length],
    ['\t', (line.match(/\t/g) || []).length],
    [';', (line.match(/;/g) || []).length],
    ['|', (line.match(/\|/g) || []).length],
  ]
  return counts.sort((a, b) => b[1] - a[1])[0][0]
}

/** Parse CSV / TSV / pasted tabular text into ParsedAsset rows. */
export function parsePortfolioText(text: string, source = 'pasted list'): ImportResult {
  const warnings: string[] = []
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && !l.startsWith('#'))

  if (lines.length === 0) {
    return { assets: [], warnings: ['No rows found in input.'], detectedColumns: {}, source }
  }

  const delim = detectDelim(lines[0])
  const header = splitLine(lines[0], delim)

  // The first row is a header only if it reads like column names: it matches
  // several known aliases and carries no data signatures (no asset-type token,
  // no magnitudes like "50 MW").
  const headerHits = header.filter((h) => Object.values(COLUMN_ALIASES).some((re) => re.test(h))).length
  const hasMagnitude = header.some((h) => /\d/.test(h))
  const hasTypeToken = header.some((h) => /bess|solar|wind|batter|flex|photovolt|\bev\b|v2g|turbine/i.test(h))
  const looksLikeHeader = headerHits >= 2 && !hasMagnitude && !hasTypeToken

  const detectedColumns: Record<string, string> = {}
  const colIndex: Partial<Record<keyof typeof COLUMN_ALIASES, number>> = {}
  if (looksLikeHeader) {
    for (const [field, re] of Object.entries(COLUMN_ALIASES)) {
      const idx = header.findIndex((h) => re.test(h))
      if (idx >= 0 && colIndex[field as keyof typeof COLUMN_ALIASES] == null) {
        colIndex[field as keyof typeof COLUMN_ALIASES] = idx
        detectedColumns[field] = header[idx]
      }
    }
  }

  const rows = looksLikeHeader ? lines.slice(1) : lines
  const assets: ParsedAsset[] = []

  rows.forEach((line, i) => {
    const cells = splitLine(line, delim)
    if (cells.every((c) => c === '')) return

    const at = (f: keyof typeof COLUMN_ALIASES) => {
      const idx = colIndex[f]
      return idx != null ? cells[idx] : undefined
    }

    // Fall back to positional guessing when there's no usable header.
    const name = (at('asset_id') ?? cells[0] ?? `Asset ${i + 1}`).trim() || `Asset ${i + 1}`
    const typeRaw = at('asset_type') ?? cells.find((c) => /bess|solar|wind|ev|flex|batter|load|turbine|v2g/i.test(c)) ?? name
    const { type, confidence: typeConf } = inferType(typeRaw)

    // Power: header column first, else a unit-tagged "MW" cell, else first numeric cell.
    const mwhCell = cells.find((c) => /mwh|kwh/i.test(c))
    const mwCell = cells.find((c) => /\bmw\b/i.test(c) && !/mwh/i.test(c))
    const mw =
      NUM(at('rated_mw')) ??
      NUM(mwCell) ??
      NUM(cells.find((c) => /\d/.test(c) && !/mwh/i.test(c) && !/(19|20)\d{2}/.test(c)))

    // Energy: header column, else a unit-tagged "MWh" cell. A column that means
    // duration (hours) is converted to MWh via the power rating.
    let mwh = NUM(at('rated_mwh')) ?? NUM(mwhCell)
    const mwhHeaderName = detectedColumns['rated_mwh']
    const mwhIsDuration = mwhHeaderName
      ? /durat|\bh(r|rs|our|ours)\b/i.test(mwhHeaderName) && !/wh/i.test(mwhHeaderName)
      : mwhCell != null && /\bh(r|rs|our|ours)\b/i.test(mwhCell) && !/wh/i.test(mwhCell)
    if (mwh != null && mwhIsDuration && mw) mwh = mwh * mw

    const chemistry = inferChemistry(at('chemistry') ?? cells.find((c) => /lfp|nmc|nca/i.test(c)) ?? typeRaw ?? '')
    const region = (at('region') ?? cells.find((c) => /caiso|ercot|pjm|miso|nyiso|iso-?ne|sp15|np15|west|north|south/i.test(c)) ?? 'Unspecified').trim()
    const year = NUM(cells.find((c) => /(19|20)\d{2}/.test(c)) ?? at('year'))

    if (mw == null || mw <= 0) {
      warnings.push(`Skipped "${name}" — no power rating (MW) found.`)
      return
    }

    // Row confidence: start from type confidence, dock for missing metadata.
    let confidence = typeConf
    if ((type === 'BESS' || type === 'EV_Fleet') && mwh == null) confidence -= 0.12
    if (region === 'Unspecified') confidence -= 0.08
    if (!colIndex.rated_mw) confidence -= 0.06
    confidence = Math.max(0.5, Math.min(0.98, +confidence.toFixed(2)))

    assets.push({
      asset_id: name,
      asset_type: type,
      rated_mw: +mw.toFixed(1),
      rated_mwh: mwh != null ? +mwh.toFixed(1) : null,
      chemistry,
      region: region || 'Unspecified',
      commissioned_year: year && year > 1990 && year < 2100 ? year : null,
      confidence,
    })
  })

  if (assets.length === 0 && warnings.length === 0)
    warnings.push('Could not parse any assets — expected columns like Name, Type, MW, MWh, Region.')

  return { assets, warnings, detectedColumns, source }
}

/** Read an uploaded File (CSV/TXT) and parse it. */
export async function parsePortfolioFile(file: File): Promise<ImportResult> {
  const text = await file.text()
  return parsePortfolioText(text, file.name)
}

// ── Sample portfolios ───────────────────────────────────────────────────────────

export type SamplePortfolio = {
  id: string
  name: string
  blurb: string
  iso: string
  assets: ParsedAsset[]
}

const A = (
  asset_id: string,
  asset_type: DemoAssetType,
  rated_mw: number,
  rated_mwh: number | null,
  chemistry: Chemistry | null,
  region: string,
  commissioned_year: number | null,
  confidence = 0.92,
): ParsedAsset => ({ asset_id, asset_type, rated_mw, rated_mwh, chemistry, region, commissioned_year, confidence })

export const SAMPLE_PORTFOLIOS: SamplePortfolio[] = [
  {
    id: 'caiso-mixed',
    name: 'Coastal hybrid fleet',
    blurb: 'Storage + solar + flexible load across CAISO NP15/SP15 — the classic California stack.',
    iso: 'CAISO',
    assets: [
      A('Hornsdale Reserve', 'BESS', 50, 100, 'LFP', 'CAISO NP15', 2021),
      A('Moss Landing Bank 3', 'BESS', 30, 120, 'NMC', 'CAISO SP15', 2020),
      A('Topaz Solar Farm', 'Solar', 45, null, null, 'CAISO SP15', 2014),
      A('Daggett Solar', 'Solar', 22, null, null, 'CAISO SP15', 2022),
      A('Bay Logistics EV Depots', 'EV_Fleet', 12, 36, 'LFP', 'CAISO NP15', 2023),
      A('Mission Campus Flex', 'Flex_Load', 10, null, null, 'CAISO NP15', 2019),
    ],
  },
  {
    id: 'ercot-wind',
    name: 'West Texas wind + storage',
    blurb: 'Wind-heavy ERCOT portfolio pairing co-located storage for ancillary services.',
    iso: 'ERCOT',
    assets: [
      A('Roscoe Wind', 'Wind', 110, null, null, 'ERCOT West', 2009),
      A('Sweetwater Wind', 'Wind', 85, null, null, 'ERCOT West', 2012),
      A('Notrees Storage', 'BESS', 36, 24, 'LFP', 'ERCOT West', 2021),
      A('Permian Flex Block', 'Flex_Load', 25, null, null, 'ERCOT West', 2020),
      A('Midland Depot V2G', 'EV_Fleet', 8, 20, 'NMC', 'ERCOT North', 2023),
    ],
  },
  {
    id: 'pjm-commercial',
    name: 'Commercial DR aggregation',
    blurb: 'Behind-the-meter flex load + EV charging + rooftop solar across PJM.',
    iso: 'PJM',
    assets: [
      A('Newark DC Flex', 'Flex_Load', 18, null, null, 'PJM DPL', 2018),
      A('Cherry Hill Mall HVAC', 'Flex_Load', 6, null, null, 'PJM PSEG', 2017),
      A('Trenton Transit EV', 'EV_Fleet', 9, 27, 'LFP', 'PJM PSEG', 2022),
      A('Logan Rooftop Solar', 'Solar', 14, null, null, 'PJM PECO', 2020),
      A('Camden Microgrid BESS', 'BESS', 10, 40, 'LFP', 'PJM AECO', 2023),
    ],
  },
]

/** A small CSV string used for the "download a template" affordance. */
export const TEMPLATE_CSV = `asset_id,asset_type,rated_mw,rated_mwh,chemistry,region,commissioned_year
Hornsdale Reserve,BESS,50,100,LFP,CAISO NP15,2021
Topaz Solar Farm,Solar,45,,,CAISO SP15,2014
Roscoe Wind,Wind,110,,,ERCOT West,2009
Bay Logistics EV Depots,EV_Fleet,12,36,LFP,CAISO NP15,2023
Mission Campus Flex,Flex_Load,10,,,CAISO NP15,2019`

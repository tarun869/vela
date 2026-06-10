import { useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BatteryCharging,
  Building2,
  CheckCircle2,
  CircleDollarSign,
  ClipboardPaste,
  Download,
  FileSpreadsheet,
  FileText,
  Gauge,
  Layers,
  Loader2,
  ShieldCheck,
  SunMedium,
  Target,
  Trash2,
  TrendingUp,
  Upload,
  Wind,
  Zap,
} from 'lucide-react'
import type { DemoAssetType } from '../types/demo'
import { extractPortfolio } from '../services/demoApi'
import { ReportStage } from './OnboardReport'
import {
  analyzePortfolio,
  type ParsedAsset,
  type PortfolioReport,
} from '../backend/onboardAnalysis'
import {
  parsePortfolioFile,
  parsePortfolioText,
  SAMPLE_PORTFOLIOS,
  TEMPLATE_CSV,
  type ImportResult,
} from '../backend/portfolioImport'

type PageId = string

const ASSET_ICON: Record<DemoAssetType, typeof BatteryCharging> = {
  BESS: BatteryCharging,
  Solar: SunMedium,
  Wind: Wind,
  EV_Fleet: Zap,
  Flex_Load: Activity,
}

const ASSET_TYPES: DemoAssetType[] = ['BESS', 'Solar', 'Wind', 'EV_Fleet', 'Flex_Load']

type Stage = 'upload' | 'review' | 'report'

export function OnboardPage({ goToPage }: { goToPage: (id: PageId) => void }) {
  const [stage, setStage] = useState<Stage>('upload')
  const [parsed, setParsed] = useState<ParsedAsset[]>([])
  const [importMeta, setImportMeta] = useState<ImportResult | null>(null)
  const [pasteText, setPasteText] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [report, setReport] = useState<PortfolioReport | null>(null)
  const [over, setOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const ingest = (res: ImportResult) => {
    if (res.assets.length === 0) {
      setImportMeta(res)
      setBusy(null)
      return
    }
    setParsed(res.assets)
    setImportMeta(res)
    setStage('review')
    setBusy(null)
  }

  const handleFile = async (file: File) => {
    setBusy(`Reading ${file.name}…`)
    const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name)
    try {
      if (isPdf) {
        // Try the Claude extraction backend; fall back to a friendly note.
        try {
          const review = await extractPortfolio([file])
          const assets: ParsedAsset[] = review.result.assets.map((a) => ({
            asset_id: a.asset_id,
            asset_type: a.asset_type,
            rated_mw: a.rated_mw,
            rated_mwh: a.rated_mwh,
            chemistry: a.chemistry,
            region: a.iso_node ?? 'Imported',
            commissioned_year: a.commissioned_date ? Number(a.commissioned_date.slice(0, 4)) || null : null,
            confidence: a.confidence,
          }))
          ingest({
            assets,
            warnings: review.result.extraction_warnings ?? [],
            detectedColumns: {},
            source: file.name,
          })
        } catch {
          setImportMeta({
            assets: [],
            warnings: [
              `Couldn't reach the document-extraction service for "${file.name}". Paste the asset list below or load a sample portfolio to continue the assessment.`,
            ],
            detectedColumns: {},
            source: file.name,
          })
          setBusy(null)
        }
      } else {
        ingest(await parsePortfolioFile(file))
      }
    } catch (err) {
      setImportMeta({
        assets: [],
        warnings: [`Failed to read file: ${err instanceof Error ? err.message : 'unknown error'}`],
        detectedColumns: {},
        source: file.name,
      })
      setBusy(null)
    }
  }

  const runAssessment = () => {
    setBusy('Modeling revenue across market products…')
    // Small timeout so the loading state reads as real work during the demo.
    window.setTimeout(() => {
      setReport(analyzePortfolio(parsed))
      setStage('report')
      setBusy(null)
    }, 650)
  }

  const restart = () => {
    setParsed([])
    setImportMeta(null)
    setReport(null)
    setPasteText('')
    setStage('upload')
  }

  return (
    <>
      <OnboardHeader stage={stage} />
      {busy && (
        <section className="panel onboard-busy">
          <Loader2 size={15} className="spin" /> {busy}
        </section>
      )}

      {stage === 'upload' && (
        <UploadStage
          over={over}
          setOver={setOver}
          fileRef={fileRef}
          onFile={handleFile}
          pasteText={pasteText}
          setPasteText={setPasteText}
          onPaste={() => ingest(parsePortfolioText(pasteText))}
          onSample={(assets, name) =>
            ingest({ assets, warnings: [], detectedColumns: {}, source: name })
          }
          warnings={importMeta?.warnings ?? []}
        />
      )}

      {stage === 'review' && (
        <ReviewStage
          parsed={parsed}
          setParsed={setParsed}
          meta={importMeta}
          onBack={restart}
          onRun={runAssessment}
        />
      )}

      {stage === 'report' && report && (
        <ReportStage report={report} parsed={parsed} onBack={() => setStage('review')} goToPage={goToPage} />
      )}
    </>
  )
}

// ── Header with progress ────────────────────────────────────────────────────────

function OnboardHeader({ stage }: { stage: Stage }) {
  const steps: { id: Stage; label: string }[] = [
    { id: 'upload', label: 'Import portfolio' },
    { id: 'review', label: 'Review assets' },
    { id: 'report', label: 'Revenue assessment' },
  ]
  const idx = steps.findIndex((s) => s.id === stage)
  return (
    <div className="page-header onboard-header">
      <div>
        <p className="demo-eyebrow">Vela onboarding</p>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: '2px 0 0' }}>DER portfolio assessment</h1>
        <p style={{ color: 'var(--muted)', fontSize: 13, margin: '4px 0 0', maxWidth: 600 }}>
          Upload the spreadsheet, interconnection PDF, or asset list you already keep today. Vela
          reads it, models what the fleet could earn across every market product, and scores how
          ready it is to participate — no integration required to get the number.
        </p>
      </div>
      <ol className="onboard-steps">
        {steps.map((s, i) => (
          <li key={s.id} className={i === idx ? 'active' : i < idx ? 'done' : ''}>
            <span className="onboard-step-dot">{i < idx ? <CheckCircle2 size={13} /> : i + 1}</span>
            {s.label}
          </li>
        ))}
      </ol>
    </div>
  )
}

// ── Stage 1: upload ─────────────────────────────────────────────────────────────

function UploadStage({
  over,
  setOver,
  fileRef,
  onFile,
  pasteText,
  setPasteText,
  onPaste,
  onSample,
  warnings,
}: {
  over: boolean
  setOver: (v: boolean) => void
  fileRef: React.RefObject<HTMLInputElement | null>
  onFile: (f: File) => void
  pasteText: string
  setPasteText: (v: string) => void
  onPaste: () => void
  onSample: (assets: ParsedAsset[], name: string) => void
  warnings: string[]
}) {
  const downloadTemplate = () => {
    const blob = new Blob([TEMPLATE_CSV], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'vela-portfolio-template.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="onboard-upload-grid">
      <div className="onboard-upload-main">
        <section
          className={`demo-dropzone onboard-drop${over ? ' over' : ''}`}
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            const f = e.dataTransfer.files?.[0]
            if (f) onFile(f)
          }}
        >
          <div className="onboard-drop-inner">
            <div className="onboard-drop-icon">
              <Upload size={26} />
            </div>
            <strong>Drop your portfolio file here</strong>
            <span>or click to browse — CSV, Excel export, TXT, or interconnection PDF</span>
            <div className="onboard-fmt-row">
              <span className="onboard-fmt"><FileSpreadsheet size={12} /> CSV / XLSX</span>
              <span className="onboard-fmt"><FileText size={12} /> PDF</span>
              <span className="onboard-fmt"><ClipboardPaste size={12} /> Pasted list</span>
            </div>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.txt,.tsv,.pdf,application/pdf,text/csv,text/plain"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onFile(f)
              e.target.value = ''
            }}
          />
        </section>

        {warnings.length > 0 && (
          <section className="panel onboard-warnbox">
            {warnings.map((w, i) => (
              <p key={i}>
                <AlertTriangle size={13} /> {w}
              </p>
            ))}
          </section>
        )}

        <section className="panel onboard-paste-panel">
          <div className="panel-head">
            <div>
              <p className="label">No file handy?</p>
              <h2>Paste your asset list</h2>
            </div>
            <button className="onboard-import" onClick={downloadTemplate}>
              <Download size={13} /> CSV template
            </button>
          </div>
          <div style={{ paddingTop: 12 }}>
            <textarea
              className="onboard-textarea"
              placeholder={
                'Paste rows like:\nHornsdale Reserve, BESS, 50 MW, 100 MWh, LFP, CAISO NP15\nTopaz Solar Farm, Solar, 45 MW, , , CAISO SP15\nRoscoe Wind, Wind, 110 MW, , , ERCOT West'
              }
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              rows={6}
            />
            <button className="btn" disabled={pasteText.trim().length === 0} onClick={onPaste} style={{ marginTop: 10 }}>
              Parse list <ArrowRight size={15} />
            </button>
          </div>
        </section>
      </div>

      <aside className="onboard-upload-side">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Start fast</p>
              <h2>Load a sample portfolio</h2>
            </div>
          </div>
          <div className="onboard-samples">
            {SAMPLE_PORTFOLIOS.map((s) => {
              const mw = s.assets.reduce((a, x) => a + x.rated_mw, 0)
              return (
                <button key={s.id} className="onboard-sample-card" onClick={() => onSample(s.assets, s.name)}>
                  <div className="onboard-sample-head">
                    <strong>{s.name}</strong>
                    <span className="onboard-iso-chip">{s.iso}</span>
                  </div>
                  <p>{s.blurb}</p>
                  <div className="onboard-sample-meta">
                    <span>{s.assets.length} assets</span>
                    <span>{mw.toFixed(0)} MW</span>
                    <ArrowRight size={13} />
                  </div>
                </button>
              )
            })}
          </div>
        </section>

        <section className="panel onboard-trust">
          <div className="panel-head">
            <div>
              <p className="label">What you get back</p>
              <h2>In one pass</h2>
            </div>
          </div>
          <ul className="onboard-trust-list">
            <li><CircleDollarSign size={14} /> Stacked annual revenue across every eligible market product</li>
            <li><TrendingUp size={14} /> Uplift vs. what the fleet earns on a single program today</li>
            <li><ShieldCheck size={14} /> Market-readiness score with the gaps that block enrollment</li>
            <li><Target size={14} /> Prioritized actions ranked by dollar impact</li>
          </ul>
        </section>
      </aside>
    </div>
  )
}

// ── Stage 2: review ─────────────────────────────────────────────────────────────

function ReviewStage({
  parsed,
  setParsed,
  meta,
  onBack,
  onRun,
}: {
  parsed: ParsedAsset[]
  setParsed: React.Dispatch<React.SetStateAction<ParsedAsset[]>>
  meta: ImportResult | null
  onBack: () => void
  onRun: () => void
}) {
  const totalMw = parsed.reduce((s, a) => s + a.rated_mw, 0)
  const totalMwh = parsed.reduce((s, a) => s + (a.rated_mwh ?? 0), 0)
  const avgConf = parsed.length ? parsed.reduce((s, a) => s + a.confidence, 0) / parsed.length : 0
  const lowConf = parsed.filter((a) => a.confidence < 0.75).length

  const update = (i: number, patch: Partial<ParsedAsset>) =>
    setParsed((prev) => prev.map((a, idx) => (idx === i ? { ...a, ...patch, confidence: Math.max(a.confidence, 0.9) } : a)))
  const remove = (i: number) => setParsed((prev) => prev.filter((_, idx) => idx !== i))

  return (
    <>
      <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <MiniStat icon={Layers} label="Assets parsed" value={String(parsed.length)} sub={meta?.source ?? 'imported'} />
        <MiniStat icon={BatteryCharging} label="Total power" value={`${totalMw.toFixed(0)} MW`} sub={`${totalMwh.toFixed(0)} MWh storage`} />
        <MiniStat
          icon={Gauge}
          label="Import confidence"
          value={`${Math.round(avgConf * 100)}%`}
          sub={lowConf ? `${lowConf} need review` : 'all clear'}
          warn={lowConf > 0}
        />
        <MiniStat
          icon={Building2}
          label="Markets"
          value={String(new Set(parsed.map((a) => a.region.split(' ')[0])).size)}
          sub={[...new Set(parsed.map((a) => a.region.split(' ')[0]))].slice(0, 3).join(', ')}
        />
      </div>

      {meta && (meta.warnings.length > 0 || Object.keys(meta.detectedColumns).length > 0) && (
        <section className="panel onboard-detect">
          {Object.keys(meta.detectedColumns).length > 0 && (
            <p className="onboard-detect-cols">
              <CheckCircle2 size={13} /> Mapped columns:{' '}
              {Object.entries(meta.detectedColumns).map(([k, v]) => (
                <span key={k} className="onboard-col-chip">
                  {v} → {k}
                </span>
              ))}
            </p>
          )}
          {meta.warnings.map((w, i) => (
            <p key={i} className="onboard-detect-warn">
              <AlertTriangle size={13} /> {w}
            </p>
          ))}
        </section>
      )}

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Step 2</p>
            <h2>Review &amp; correct the parsed fleet</h2>
          </div>
          <span className="label" style={{ textTransform: 'none', fontWeight: 600 }}>
            Edit any cell — fixes raise confidence
          </span>
        </div>
        <div style={{ padding: '0 14px 14px', overflowX: 'auto' }}>
          <table className="roster-table review-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Type</th>
                <th>MW</th>
                <th>MWh</th>
                <th>Region / node</th>
                <th>Confidence</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {parsed.map((a, i) => {
                const Icon = ASSET_ICON[a.asset_type]
                return (
                  <tr key={`${a.asset_id}-${i}`} className={a.confidence < 0.75 ? 'demo-row-amber' : ''}>
                    <td>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Icon size={15} color="var(--green)" />
                        <input
                          className="review-input"
                          value={a.asset_id}
                          onChange={(e) => update(i, { asset_id: e.target.value })}
                        />
                      </span>
                    </td>
                    <td>
                      <select
                        className="review-input review-select"
                        value={a.asset_type}
                        onChange={(e) => update(i, { asset_type: e.target.value as DemoAssetType })}
                      >
                        {ASSET_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t.replace('_', ' ')}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input
                        className="review-input review-num"
                        type="number"
                        value={a.rated_mw}
                        onChange={(e) => update(i, { rated_mw: Math.max(0, Number(e.target.value)) })}
                      />
                    </td>
                    <td>
                      <input
                        className="review-input review-num"
                        type="number"
                        placeholder="—"
                        value={a.rated_mwh ?? ''}
                        onChange={(e) =>
                          update(i, { rated_mwh: e.target.value === '' ? null : Math.max(0, Number(e.target.value)) })
                        }
                      />
                    </td>
                    <td>
                      <input
                        className="review-input"
                        value={a.region}
                        onChange={(e) => update(i, { region: e.target.value })}
                      />
                    </td>
                    <td>
                      <span className={`conf-pill ${a.confidence >= 0.85 ? 'good' : a.confidence >= 0.7 ? 'mid' : 'low'}`}>
                        {Math.round(a.confidence * 100)}%
                      </span>
                    </td>
                    <td>
                      <button className="icon-btn" title="Remove" onClick={() => remove(i)}>
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel onboard-actionbar">
        <button className="btn-ghost" onClick={onBack}>
          <ArrowLeft size={15} /> Start over
        </button>
        <button className="btn btn-lg" disabled={parsed.length === 0} onClick={onRun}>
          Run revenue assessment <ArrowRight size={16} />
        </button>
      </section>
    </>
  )
}

function MiniStat({
  icon: Icon,
  label,
  value,
  sub,
  warn,
}: {
  icon: typeof BatteryCharging
  label: string
  value: string
  sub: string
  warn?: boolean
}) {
  return (
    <section className="metric-card">
      <div className="metric-icon" style={warn ? { color: 'var(--amber)' } : undefined}>
        <Icon size={18} />
      </div>
      <div>
        <p className="label">{label}</p>
        <strong>{value}</strong>
        <span style={warn ? { color: 'var(--amber)' } : undefined}>{sub}</span>
      </div>
    </section>
  )
}

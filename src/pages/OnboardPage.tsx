import { useState, useRef, useCallback } from 'react'
import {
  FileText,
  Upload,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  ChevronRight,
  X,
} from 'lucide-react'
import type {
  DemoAssetIn,
  DemoAssetType,
  Chemistry,
  ExtractionReview,
  ExtractedAsset,
  ExtractedObligation,
} from '../types/demo'
import { extractPortfolio, startDemoFleet } from '../services/demoApi'

type PageId = string

const CONFIDENCE_THRESHOLD = 0.85

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function confidenceBadge(conf: number) {
  const pct = Math.round(conf * 100)
  const color = conf >= CONFIDENCE_THRESHOLD ? 'var(--green)' : 'var(--amber)'
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        color,
        background: conf >= CONFIDENCE_THRESHOLD ? 'var(--green-soft)' : 'var(--amber-soft)',
        padding: '1px 6px',
        borderRadius: 4,
      }}
    >
      {pct}%
    </span>
  )
}

type DrawerItem =
  | { kind: 'asset'; item: ExtractedAsset; idx: number }
  | { kind: 'obligation'; item: ExtractedObligation; idx: number }

function DropZone({
  label,
  hint,
  file,
  onFile,
}: {
  label: string
  hint: string
  file: File | null
  onFile: (f: File) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setOver(false)
      const f = e.dataTransfer.files[0]
      if (f && f.type === 'application/pdf') onFile(f)
    },
    [onFile],
  )

  return (
    <div
      className={`demo-dropzone${over ? ' over' : ''}${file ? ' filled' : ''}`}
      onDragOver={e => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click() }}
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        style={{ display: 'none' }}
        onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f) }}
      />
      {file ? (
        <div className="demo-dropzone-filled">
          <FileText size={20} color="var(--green)" />
          <div>
            <strong>{file.name}</strong>
            <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>
              {formatBytes(file.size)}
            </span>
          </div>
          <CheckCircle2 size={16} color="var(--green)" style={{ marginLeft: 'auto' }} />
        </div>
      ) : (
        <div className="demo-dropzone-empty">
          <Upload size={20} color="var(--muted)" />
          <strong>{label}</strong>
          <span>{hint}</span>
        </div>
      )}
    </div>
  )
}

export function OnboardPage({ goToPage }: { goToPage: (id: PageId) => void }) {
  const [portfolioFile, setPortfolioFile] = useState<File | null>(null)
  const [contractFile, setContractFile] = useState<File | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [extractError, setExtractError] = useState<string | null>(null)
  const [review, setReview] = useState<ExtractionReview | null>(null)
  const [drawer, setDrawer] = useState<DrawerItem | null>(null)
  const [editValues, setEditValues] = useState<Record<string, string>>({})
  const [confirmedKeys, setConfirmedKeys] = useState<Set<string>>(new Set())
  const [connecting, setConnecting] = useState(false)

  const files = [portfolioFile, contractFile].filter((f): f is File => f !== null)
  const canExtract = files.length > 0 && !extracting

  const handleExtract = async () => {
    setExtracting(true)
    setExtractError(null)
    try {
      const result = await extractPortfolio(files)
      setReview(result)
    } catch (err) {
      setExtractError(err instanceof Error ? err.message : 'Extraction failed')
    } finally {
      setExtracting(false)
    }
  }

  const flaggedAssets = review?.result.assets.filter(a => a.confidence < CONFIDENCE_THRESHOLD) ?? []
  const flaggedObligations = review?.result.obligations.filter(o => o.ambiguous_language !== null) ?? []
  const totalFlagged = flaggedAssets.length + flaggedObligations.length
  const allReviewed = confirmedKeys.size >= totalFlagged

  const confirmKey = (key: string) => {
    setConfirmedKeys(prev => new Set([...prev, key]))
    setDrawer(null)
  }

  const handleConnect = async () => {
    if (!review) return
    setConnecting(true)
    try {
      const demoAssets: DemoAssetIn[] = review.result.assets.map(a => ({
        asset_id: a.asset_id,
        asset_type: a.asset_type as DemoAssetType,
        rated_mw: a.rated_mw,
        rated_mwh: a.rated_mwh,
        chemistry: (a.chemistry ?? null) as Chemistry | null,
      }))
      await startDemoFleet(demoAssets)
      goToPage('fleet')
    } catch (err) {
      setExtractError(err instanceof Error ? err.message : 'Fleet connect failed')
    } finally {
      setConnecting(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <p className="label" style={{ fontFamily: 'var(--mono)', textTransform: 'uppercase', fontSize: 10, letterSpacing: '0.08em', color: 'var(--muted)' }}>Demo flow · Step 1 of 4</p>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Onboard portfolio</h1>
        </div>
      </div>

      <div className="demo-onboard-layout">
        {/* ── Left: upload panel ── */}
        <div className="demo-upload-col">
          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="label">Upload documents</p>
                <h2>Portfolio &amp; contracts</h2>
              </div>
            </div>

            <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
              <DropZone
                label="Asset Portfolio"
                hint="Interconnection agreement or asset register PDF"
                file={portfolioFile}
                onFile={setPortfolioFile}
              />
              <DropZone
                label="Contracts &amp; Obligations"
                hint="Commercial obligations or capacity contract PDF"
                file={contractFile}
                onFile={setContractFile}
              />

              {extractError && (
                <p style={{ color: 'var(--red)', fontSize: 12, margin: 0 }}>
                  <AlertTriangle size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
                  {extractError}
                </p>
              )}

              <button
                className="btn"
                disabled={!canExtract}
                onClick={() => { void handleExtract() }}
                style={{ marginTop: 4 }}
              >
                {extracting ? (
                  <>
                    <Loader2 size={15} className="spin" />
                    Reading documents…
                  </>
                ) : (
                  'Extract with Vela'
                )}
              </button>
            </div>
          </section>

          {review && (
            <section className="panel" style={{ marginTop: 0 }}>
              <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                <p className="label" style={{ margin: 0 }}>
                  {review.result.assets.length} assets · {review.result.obligations.length} obligations
                  {totalFlagged > 0 && (
                    <span style={{ color: 'var(--amber)', marginLeft: 8 }}>
                      · {totalFlagged - confirmedKeys.size} fields need review
                    </span>
                  )}
                  {totalFlagged === 0 && (
                    <span style={{ color: 'var(--green)', marginLeft: 8 }}>· All fields look good</span>
                  )}
                </p>
                <button
                  className="btn"
                  disabled={!allReviewed || connecting}
                  onClick={() => { void handleConnect() }}
                >
                  {connecting ? (
                    <><Loader2 size={15} className="spin" /> Connecting…</>
                  ) : (
                    <>Connect Fleet <ChevronRight size={14} /></>
                  )}
                </button>
              </div>
            </section>
          )}
        </div>

        {/* ── Right: results ── */}
        {review && (
          <div className="demo-results-col">
            {review.result.assets.length > 0 && (
              <section className="panel">
                <div className="panel-head">
                  <div>
                    <p className="label">Extracted assets</p>
                    <h2>{review.result.assets.length} assets found</h2>
                  </div>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table className="roster-table">
                    <thead>
                      <tr>
                        <th>Asset ID</th>
                        <th>Type</th>
                        <th>MW</th>
                        <th>MWh</th>
                        <th>Node</th>
                        <th>Chemistry</th>
                        <th>Warranty</th>
                        <th>Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {review.result.assets.map((asset, idx) => {
                        const key = `asset-${idx}`
                        const flagged = asset.confidence < CONFIDENCE_THRESHOLD
                        const confirmed = confirmedKeys.has(key)
                        return (
                          <tr
                            key={key}
                            className={flagged && !confirmed ? 'demo-row-warn' : ''}
                            style={{ cursor: flagged ? 'pointer' : 'default' }}
                            onClick={() => flagged && setDrawer({ kind: 'asset', item: asset, idx })}
                          >
                            <td><strong>{asset.asset_id}</strong></td>
                            <td>{asset.asset_type}</td>
                            <td>{asset.rated_mw}</td>
                            <td>{asset.rated_mwh ?? '—'}</td>
                            <td>{asset.iso_node ?? '—'}</td>
                            <td>{asset.chemistry ?? '—'}</td>
                            <td>{asset.warranty_cycles != null ? `${asset.warranty_cycles} cy` : '—'}</td>
                            <td>{confidenceBadge(asset.confidence)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {review.result.obligations.length > 0 && (
              <section className="panel">
                <div className="panel-head">
                  <div>
                    <p className="label">Extracted obligations</p>
                    <h2>{review.result.obligations.length} obligations found</h2>
                  </div>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table className="roster-table">
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th>Committed MW</th>
                        <th>Window</th>
                        <th>Penalty Rate</th>
                        <th>Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {review.result.obligations.map((obl, idx) => {
                        const key = `obl-${idx}`
                        const flagged = obl.ambiguous_language !== null
                        const confirmed = confirmedKeys.has(key)
                        const window = obl.delivery_windows[0]
                        return (
                          <tr
                            key={key}
                            className={flagged && !confirmed ? 'demo-row-amber' : ''}
                            style={{ cursor: flagged ? 'pointer' : 'default' }}
                            onClick={() => flagged && setDrawer({ kind: 'obligation', item: obl, idx })}
                          >
                            <td><strong>{obl.obligation_type}</strong></td>
                            <td>{obl.committed_mw} MW</td>
                            <td>
                              {window
                                ? `${window.start_hour}:00–${window.end_hour}:00`
                                : '—'}
                            </td>
                            <td>
                              {obl.penalty_linear_per_mwh != null
                                ? `$${obl.penalty_linear_per_mwh}/MWh`
                                : '—'}
                            </td>
                            <td>{confidenceBadge(obl.confidence)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {review.result.extraction_warnings.length > 0 && (
              <section className="panel">
                <div style={{ padding: '12px 16px' }}>
                  {review.result.extraction_warnings.map((w, i) => (
                    <p key={i} style={{ fontSize: 12, color: 'var(--amber)', margin: '4px 0' }}>
                      <AlertTriangle size={11} style={{ verticalAlign: 'middle', marginRight: 4 }} />
                      {w}
                    </p>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </div>

      {/* ── Review drawer ── */}
      {drawer && (
        <div className="demo-drawer-backdrop" onClick={() => setDrawer(null)}>
          <div className="demo-drawer" onClick={e => e.stopPropagation()}>
            <div className="demo-drawer-head">
              <strong>Review field</strong>
              <button className="icon-btn" onClick={() => setDrawer(null)}><X size={14} /></button>
            </div>

            {drawer.kind === 'asset' && (
              <ReviewDrawerContent
                title={`Asset: ${drawer.item.asset_id}`}
                confidence={drawer.item.confidence}
                sourceText={drawer.item.source_text}
                fields={[
                  { label: 'Asset type', value: String(drawer.item.asset_type) },
                  { label: 'Rated MW', value: String(drawer.item.rated_mw) },
                  { label: 'Rated MWh', value: String(drawer.item.rated_mwh ?? '') },
                  { label: 'ISO Node', value: drawer.item.iso_node ?? '' },
                  { label: 'Chemistry', value: drawer.item.chemistry ?? '' },
                ]}
                editValues={editValues}
                onChange={(field, val) => setEditValues(prev => ({ ...prev, [`asset-${drawer.idx}-${field}`]: val }))}
                keyPrefix={`asset-${drawer.idx}`}
                onConfirm={() => confirmKey(`asset-${drawer.idx}`)}
              />
            )}

            {drawer.kind === 'obligation' && (
              <ReviewDrawerContent
                title={`Obligation: ${drawer.item.obligation_type}`}
                confidence={drawer.item.confidence}
                sourceText={drawer.item.source_text}
                ambiguous={drawer.item.ambiguous_language}
                fields={[
                  { label: 'Committed MW', value: String(drawer.item.committed_mw) },
                  { label: 'Penalty rate', value: drawer.item.penalty_linear_per_mwh != null ? String(drawer.item.penalty_linear_per_mwh) : '' },
                ]}
                editValues={editValues}
                onChange={(field, val) => setEditValues(prev => ({ ...prev, [`obl-${drawer.idx}-${field}`]: val }))}
                keyPrefix={`obl-${drawer.idx}`}
                onConfirm={() => confirmKey(`obl-${drawer.idx}`)}
              />
            )}
          </div>
        </div>
      )}
    </>
  )
}

function ReviewDrawerContent({
  title,
  confidence,
  sourceText,
  ambiguous,
  fields,
  editValues,
  onChange,
  keyPrefix,
  onConfirm,
}: {
  title: string
  confidence: number
  sourceText: string | null
  ambiguous?: string | null
  fields: { label: string; value: string }[]
  editValues: Record<string, string>
  onChange: (field: string, val: string) => void
  keyPrefix: string
  onConfirm: () => void
}) {
  return (
    <div className="demo-drawer-body">
      <p className="label">{title}</p>
      <div style={{ marginBottom: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>Confidence</span>
        {confidenceBadge(confidence)}
      </div>

      {ambiguous && (
        <div style={{ background: 'var(--amber-soft)', borderRadius: 6, padding: '8px 10px', marginBottom: 12, fontSize: 12, color: 'var(--amber)' }}>
          <strong>Ambiguous language:</strong> "{ambiguous}"
        </div>
      )}

      {sourceText && (
        <div style={{ background: 'var(--surface-2)', borderRadius: 6, padding: '8px 10px', marginBottom: 12, fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)', lineHeight: 1.5 }}>
          "{sourceText}"
        </div>
      )}

      {fields.map(({ label, value }) => {
        const fkey = `${keyPrefix}-${label}`
        return (
          <div key={fkey} style={{ marginBottom: 10 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>{label}</label>
            <input
              type="text"
              defaultValue={editValues[fkey] ?? value}
              onChange={e => onChange(label, e.target.value)}
              style={{ width: '100%', padding: '6px 8px', border: '1px solid var(--line)', borderRadius: 5, fontSize: 13, background: 'var(--surface)', color: 'var(--ink)', boxSizing: 'border-box' }}
            />
          </div>
        )
      })}

      <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
        <button className="btn" onClick={onConfirm}>Confirm</button>
        <button className="btn" style={{ background: 'var(--surface-2)', color: 'var(--ink)' }} onClick={onConfirm}>
          Looks correct
        </button>
      </div>
    </div>
  )
}

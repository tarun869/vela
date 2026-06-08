import { useState, useEffect, useRef, useCallback } from 'react'
import type {
  AssetTelemetry,
  FleetDispatchPlan,
  ObligationStatus,
  PriceTick,
  SpikeAlert,
  WSMessage,
} from '../types/demo'

export type SpikeAlertEntry = {
  id: string
  type: 'spike'
  ts: number
  data: SpikeAlert
  approved: boolean
  dismissed: boolean
}

export type ObligationAlertEntry = {
  id: string
  type: 'obligation'
  ts: number
  data: ObligationStatus
}

export type DispatchUpdateEntry = {
  id: string
  type: 'dispatch'
  ts: number
  summary: string
}

export type AlertEntry = SpikeAlertEntry | ObligationAlertEntry | DispatchUpdateEntry

export function useFleetWebSocket() {
  const [connected, setConnected] = useState(false)
  const [telemetry, setTelemetry] = useState<Record<string, AssetTelemetry>>({})
  const [sohStart, setSohStart] = useState<Record<string, number>>({})
  const [price, setPrice] = useState<PriceTick | null>(null)
  const [priceHistory, setPriceHistory] = useState<PriceTick[]>([])
  const [plan, setPlan] = useState<FleetDispatchPlan | null>(null)
  const [alerts, setAlerts] = useState<AlertEntry[]>([])
  const [spikeFlash, setSpikeFlash] = useState(false)

  const retryDelay = useRef(1000)
  const destroyed = useRef(false)

  const dismissAlert = useCallback((id: string) => {
    setAlerts(prev =>
      prev.map(a =>
        a.id === id && a.type === 'spike' ? { ...a, dismissed: true } : a,
      ),
    )
  }, [])

  const approveAlert = useCallback((id: string) => {
    setAlerts(prev =>
      prev.map(a =>
        a.id === id && a.type === 'spike' ? { ...a, approved: true } : a,
      ),
    )
  }, [])

  useEffect(() => {
    destroyed.current = false
    let ws: WebSocket | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (destroyed.current) return
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      ws = new WebSocket(`${protocol}//${location.host}/ws/fleet/telemetry`)

      ws.onopen = () => {
        setConnected(true)
        retryDelay.current = 1000
      }

      ws.onclose = () => {
        setConnected(false)
        if (!destroyed.current) {
          retryTimer = setTimeout(connect, retryDelay.current)
          retryDelay.current = Math.min(retryDelay.current * 2, 30_000)
        }
      }

      ws.onerror = () => ws?.close()

      ws.onmessage = (e: MessageEvent<string>) => {
        let msg: WSMessage
        try {
          msg = JSON.parse(e.data) as WSMessage
        } catch {
          return
        }

        if (msg.type === 'telemetry') {
          setSohStart(prev =>
            msg.data.asset_id in prev ? prev : { ...prev, [msg.data.asset_id]: msg.data.soh_pct },
          )
          setTelemetry(prev => ({ ...prev, [msg.data.asset_id]: msg.data }))
        } else if (msg.type === 'price') {
          setPrice(msg.data)
          setPriceHistory(prev => [...prev.slice(-19), msg.data])
        } else if (msg.type === 'dispatch_plan') {
          setPlan(msg.data)
          const summary = msg.data.decisions[0]?.reasoning ?? 'Plan updated'
          setAlerts(prev => [
            {
              id: crypto.randomUUID(),
              type: 'dispatch' as const,
              ts: Date.now(),
              summary,
            },
            ...prev.slice(0, 49),
          ])
        } else if (msg.type === 'spike_alert') {
          setSpikeFlash(true)
          setTimeout(() => setSpikeFlash(false), 2000)
          setAlerts(prev => [
            {
              id: crypto.randomUUID(),
              type: 'spike' as const,
              ts: Date.now(),
              data: msg.data,
              approved: false,
              dismissed: false,
            },
            ...prev.slice(0, 49),
          ])
        } else if (msg.type === 'obligation_alert') {
          setAlerts(prev => [
            {
              id: crypto.randomUUID(),
              type: 'obligation' as const,
              ts: Date.now(),
              data: msg.data,
            },
            ...prev.slice(0, 49),
          ])
        }
      }
    }

    connect()

    return () => {
      destroyed.current = true
      if (retryTimer !== null) clearTimeout(retryTimer)
      ws?.close()
    }
  }, [])

  return {
    connected,
    telemetry,
    sohStart,
    price,
    priceHistory,
    plan,
    alerts,
    spikeFlash,
    dismissAlert,
    approveAlert,
  }
}

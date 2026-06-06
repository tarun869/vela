export type AssetType = 'Battery' | 'EV charger' | 'Solar' | 'Building load' | 'Generator'

export type MarketProduct =
  | 'Energy arbitrage'
  | 'Frequency regulation'
  | 'Capacity event'
  | 'Demand response'
  | 'Reserve'

export type ActionType = 'sell' | 'store' | 'shift' | 'reserve' | 'curtail'

export type GridCondition = 'normal' | 'scarcity' | 'congested' | 'oversupply'

export type Asset = {
  id: string
  name: string
  type: AssetType
  region: string
  capacityMw: number
  availableMw: number
  stateOfCharge?: number
  readiness: number
  degradationCost: number
  customerFlex: number
  telemetry: 'healthy' | 'delayed' | 'limited'
  constraint: string
}

export type MarketSignal = {
  product: MarketProduct
  region: string
  price: number
  confidence: number
  obligationMw: number
  interval: string
  weatherSignal: string
  gridCondition: GridCondition
  risk: 'low' | 'medium' | 'high'
}

export type IntegrationSource = {
  system: string
  category: string
  signals: string
  cadence: string
  adapter: string
  health: 'healthy' | 'limited' | 'delayed'
}

export type IntegrationStandard = {
  id: string
  name: string
  domain: 'Market access' | 'DER control' | 'Distribution operations' | 'Interconnection'
  source: string
  requirement: string
  velaRecord: 'Asset' | 'TelemetrySample' | 'FlexibilityEnvelope' | 'ConstraintPolicy' | 'MarketEnrollment' | 'DispatchPlan'
  implementation: 'modeled' | 'partial' | 'missing'
  note: string
}

export type TelemetrySample = {
  assetId: string
  source: string
  timestamp: string
  realPowerMw: number
  reactivePowerMvar?: number
  stateOfCharge?: number
  breakerClosed?: boolean
  quality: 'valid' | 'estimated' | 'stale' | 'missing'
}

export type FlexibilityEnvelope = {
  assetId: string
  interval: string
  maxExportMw: number
  maxImportMw: number
  sustainedDurationMinutes: number
  rampRateMwPerMinute: number
  controlLatencySeconds: number
  telemetryLatencySeconds: number
  confidence: number
}

export type ConstraintPolicy = {
  id: string
  assetId: string
  source: string
  rule: string
  severity: 'binding' | 'advisory' | 'monitor'
  operatorApprovalRequired: boolean
}

export type MarketEnrollment = {
  id: string
  assetId: string
  program: string
  product: MarketProduct
  region: string
  status: 'active' | 'pending' | 'suspended'
  minOfferMw: number
  maxOfferMw: number
  telemetryRequirementSeconds: number
  settlementRisk: 'low' | 'medium' | 'high'
  expiresAt: string
}

export type ControlLoopCheck = {
  assetId: string
  product: MarketProduct
  interval: string
  telemetryRequirementSeconds: number
  observedLoopSeconds: number
  latencySlackSeconds: number
  rampHeadroomMw: number
  approvalRequired: boolean
  status: 'ready' | 'watch' | 'blocked'
  note: string
}

export type ScenarioVariable = {
  priceMultiplier: number
  availabilityMultiplier: number
  responseFailureProbability: number
  imbalancePenaltyMultiplier: number
  weatherDerateMw: number
}

export type DispatchScenario = {
  id: string
  label: string
  probability: number
  variables: ScenarioVariable
}

export type ObjectiveWeights = {
  revenue: number
  reliability: number
  obligation: number
  degradation: number
  customer: number
  risk: number
}

export type ObjectiveKey = keyof ObjectiveWeights

export type RiskScenario = {
  id: string
  label: string
  probability: number
  priceMultiplier: number
  availabilityMultiplier: number
  penaltyMultiplier: number
}

export type ConstraintEvaluation = {
  id: string
  label: string
  lhs: number
  operator: '<=' | '>=' | '='
  rhs: number
  slack: number
  severity: 'binding' | 'advisory' | 'monitor'
  satisfied: boolean
}

export type ObjectiveContribution = {
  key: ObjectiveKey
  label: string
  weight: number
  normalizedValue: number
  weightedValue: number
}

export type AssetDispatchAllocation = {
  assetId: string
  dispatchMw: number
  participationFactor: number
  marginalCost: number
  confidence: number
  rampFeasibleMw: number
  responseTimeSeconds: number
  latencyPenalty: number
}

export type ScenarioOutcome = {
  scenarioId: string
  label: string
  probability: number
  deliveredMw: number
  effectiveShortfallMw: number
  grossRevenue: number
  variableCost: number
  imbalancePenalty: number
  netRevenue: number
}

export type RiskContribution = {
  id: string
  label: string
  value: number
  share: number
  severity: 'low' | 'medium' | 'high'
}

export type RobustDecisionModel = {
  candidateId: string
  utility: number
  expectedRevenue: number
  downsideRevenue: number
  cvar95: number
  feasibility: number
  deterministicEquivalentMw: number
  rampFeasibleMw: number
  rampShortfallMw: number
  controlRiskPenalty: number
  reserveMargin: number
  expectedShortfallMw: number
  violationPenalty: number
  riskAdjustedScore: number
  allocations: AssetDispatchAllocation[]
  scenarioOutcomes: ScenarioOutcome[]
  riskContributions: RiskContribution[]
  objectiveContributions: ObjectiveContribution[]
  constraints: ConstraintEvaluation[]
  scenarios: DispatchScenario[]
  assumptions: string[]
}

export type SensitivityCase = {
  id: string
  label: string
  parameter: 'price' | 'confidence' | 'availability' | 'penalty'
  direction: 'down' | 'up'
  deltaPercent: number
  scoreDelta: number
  expectedRevenueDelta: number
  feasibilityDelta: number
  interpretation: string
}

export type DecisionCandidate = {
  id: string
  action: ActionType
  market: MarketSignal
  assets: Asset[]
  targetMw: number
  score: number
  revenue: number
  reliability: number
  obligationFit: number
  enrollmentFit: number
  degradationPenalty: number
  customerPenalty: number
  riskPenalty: number
  robustModel?: RobustDecisionModel
  explanation: string
  constraints: string[]
}

export type OperatorRecommendation = {
  action: ActionType
  targetMw: number
  score: number
  window: string
  headline: string
  why: string
}

export type DataQualitySignal = {
  label: string
  source: string
  freshness: string
  confidence: number
  impact: string
  status: 'healthy' | 'watch' | 'risk'
}

export type AdapterKind = 'SCADA' | 'BMS' | 'EVSE' | 'BMS gateway' | 'ISO market' | 'Weather' | 'Rules engine'

export type RawAdapterPayload = {
  id: string
  adapter: AdapterKind
  vendor: string
  receivedAt: string
  schemaVersion: string
  payload: Record<string, string | number | boolean | null>
}

export type NormalizedRecord =
  | { kind: 'telemetry'; record: TelemetrySample }
  | { kind: 'flexibility'; record: FlexibilityEnvelope }
  | { kind: 'market'; record: MarketSignal }
  | { kind: 'constraint'; record: ConstraintPolicy }

export type AdapterNormalizationResult = {
  payloadId: string
  adapter: AdapterKind
  vendor: string
  receivedAt: string
  confidence: number
  records: NormalizedRecord[]
  warnings: string[]
}

export type ValidationSeverity = 'pass' | 'watch' | 'fail'

export type ValidationFinding = {
  id: string
  severity: ValidationSeverity
  label: string
  detail: string
  affectedRecords: string[]
}

export type BidBlock = {
  product: MarketProduct
  region: string
  interval: string
  quantityMw: number
  limitPrice: number
  confidence: number
  sourceCandidateId: string
}

export type DispatchInstruction = {
  assetId: string
  action: ActionType
  interval: string
  targetMw: number
  rampRateMwPerMinute: number
  requiresApproval: boolean
  reason: string
}

export type ApprovalGate = {
  id: string
  label: string
  status: 'clear' | 'needs-review' | 'blocked'
  rationale: string
}

export type AuditEvent = {
  timestamp: string
  actor: string
  event: string
  detail: string
}

export type DispatchPlan = {
  id: string
  recommendationId: string
  mode: 'advisory'
  bidBlocks: BidBlock[]
  instructions: DispatchInstruction[]
  approvalGates: ApprovalGate[]
  auditTrail: AuditEvent[]
}

export type OperatorOverride = {
  id: string
  target: 'candidate' | 'asset' | 'market' | 'portfolio'
  targetId: string
  requestedBy: string
  createdAt: string
  reason: string
  status: 'proposed' | 'approved' | 'rejected'
  limitMw?: number
  priceFloor?: number
  expiresAt: string
}

export type OverrideImpact = {
  overrideId: string
  label: string
  status: OperatorOverride['status']
  affectedTarget: string
  targetMwBefore: number
  targetMwAfter: number
  scoreDelta: number
  approvalImpact: 'none' | 'adds-review' | 'blocks'
  rationale: string
}

export type SettlementLine = {
  id: string
  label: string
  quantityMw: number
  price: number
  amount: number
  category: 'revenue' | 'cost' | 'risk'
}

export type SettlementProjection = {
  dispatchPlanId: string
  expectedAwardMw: number
  deliveredP50Mw: number
  deliveredP05Mw: number
  grossRevenue: number
  serviceFees: number
  degradationCost: number
  imbalanceReserve: number
  netMargin: number
  marginPerMw: number
  lines: SettlementLine[]
}

export type ModelRunInputRefType =
  | 'adapter'
  | 'validation'
  | 'candidate'
  | 'dispatch'
  | 'settlement'
  | 'override'
  | 'coordination'

export type ModelRunInputRef = {
  id: string
  source: string
  recordType: ModelRunInputRefType
  confidence: number
  status: 'used' | 'warning' | 'blocked'
}

export type ModelRunDecisionRank = {
  candidateId: string
  action: ActionType
  product: MarketProduct
  interval: string
  score: number
  feasibility: number
  downsideRevenue: number
  dominantRisk: string
}

export type ModelRunSnapshot = {
  id: string
  createdAt: string
  modelVersion: string
  topCandidateId: string
  readinessScore: number
  evidenceConfidence: number
  inputRefs: ModelRunInputRef[]
  rankedDecisions: ModelRunDecisionRank[]
  persistenceEvents: AuditEvent[]
  decisionSummary: string
}

export type CoordinationOwner = 'RTO/ISO' | 'Distribution utility' | 'Aggregator' | 'Customer' | 'Internal'

export type CoordinationCheckpoint = {
  id: string
  label: string
  owner: CoordinationOwner
  requirement: string
  evidence: string
  status: 'ready' | 'review' | 'blocked'
  risk: 'low' | 'medium' | 'high'
  dueBy: string
}

export type CoordinationReadiness = {
  score: number
  readyCount: number
  reviewCount: number
  blockedCount: number
  checkpoints: CoordinationCheckpoint[]
}

export type ReplayCoverageItem = {
  recordType: ModelRunInputRefType
  used: number
  warnings: number
  blocked: number
  confidence: number
}

export type ReplayGap = {
  id: string
  severity: 'watch' | 'blocked'
  label: string
  detail: string
}

export type ReplayManifest = {
  runId: string
  fingerprint: string
  replayReady: boolean
  coverage: ReplayCoverageItem[]
  gaps: ReplayGap[]
  generatedAt: string
}

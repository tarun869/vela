{{/*
Expand the name of the chart.
*/}}
{{- define "vela.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
*/}}
{{- define "vela.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label.
*/}}
{{- define "vela.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "vela.labels" -}}
helm.sh/chart: {{ include "vela.chart" . }}
{{ include "vela.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: vela-vpp
{{- end }}

{{/*
Selector labels
*/}}
{{- define "vela.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vela.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Component-specific selector labels
*/}}
{{- define "vela.componentSelectorLabels" -}}
app.kubernetes.io/name: {{ include "vela.name" . }}-{{ .component }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "vela.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "vela.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Return the image for a given component
Usage: {{ include "vela.image" (dict "image" .Values.image.api "global" .Values.global) }}
*/}}
{{- define "vela.image" -}}
{{- $registry := .image.registry | default .global.imageRegistry -}}
{{- $repo := .image.repository -}}
{{- $tag := .image.tag | default "latest" -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- end }}

{{/*
Common environment variables from secrets
*/}}
{{- define "vela.commonEnvFromSecret" -}}
- name: VELA_DB_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "vela.fullname" . }}-secrets
      key: db-url
- name: VELA_REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "vela.fullname" . }}-secrets
      key: redis-url
- name: VELA_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "vela.fullname" . }}-secrets
      key: secret-key
{{- end }}

{{/*
Common resource limits
*/}}
{{- define "vela.resources" -}}
resources:
  {{- toYaml .resources | nindent 2 }}
{{- end }}

{{/*
Expand the name of the chart.
*/}}
{{- define "cardano-forge-crds.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "cardano-forge-crds.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "cardano-forge-crds.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "cardano-forge-crds.labels" -}}
helm.sh/chart: {{ include "cardano-forge-crds.chart" . }}
{{ include "cardano-forge-crds.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.global.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "cardano-forge-crds.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cardano-forge-crds.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Common annotations
*/}}
{{- define "cardano-forge-crds.annotations" -}}
{{- with .Values.global.commonAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "cardano-forge-crds.serviceAccountName" -}}
{{- if .Values.rbac.serviceAccount.create }}
{{- default (include "cardano-forge-crds.fullname" .) .Values.rbac.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.rbac.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the cluster role to use
*/}}
{{- define "cardano-forge-crds.clusterRoleName" -}}
{{- default (printf "%s-cluster-role" (include "cardano-forge-crds.fullname" .)) .Values.rbac.clusterRole.name }}
{{- end }}

{{/*
Create the name of the cluster role binding to use
*/}}
{{- define "cardano-forge-crds.clusterRoleBindingName" -}}
{{- default (printf "%s-cluster-role-binding" (include "cardano-forge-crds.fullname" .)) .Values.rbac.clusterRoleBinding.name }}
{{- end }}
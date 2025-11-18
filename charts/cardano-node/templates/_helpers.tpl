{{/*
Expand the name of the chart.
*/}}
{{- define "cardano-node.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "cardano-node.fullname" -}}
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
{{- define "cardano-node.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "cardano-node.labels" -}}
helm.sh/chart: {{ include "cardano-node.chart" . }}
{{ include "cardano-node.selectorLabels" . }}
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
{{- define "cardano-node.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cardano-node.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Values.cardanoNode.blockProducer }}
app.kubernetes.io/component: block-producer
{{- else }}
app.kubernetes.io/component: relay
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "cardano-node.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "cardano-node.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the forging keys secret to use
*/}}
{{- define "cardano-node.forgingKeysSecretName" -}}
{{- if .Values.forgeManager.secretName }}
{{- .Values.forgeManager.secretName }}
{{- else }}
{{- printf "%s-forging-keys" (include "cardano-node.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Get pool short ID for multi-tenant naming
Returns first 8-10 characters of pool ID for use in resource names
*/}}
{{- define "cardano-node.poolShortId" -}}
{{- $poolId := .Values.forgeManager.multiTenant.pool.id -}}
{{- if $poolId -}}
{{- if hasPrefix "pool1" $poolId -}}
{{- $poolId | trunc 10 -}}
{{- else if ge (len $poolId) 8 -}}
{{- $poolId | trunc 8 -}}
{{- else -}}
{{- $poolId -}}
{{- end -}}
{{- else -}}
{{- "" -}}
{{- end -}}
{{- end }}

{{/*
Generate lease name for leader election
In multi-tenant mode: cardano-leader-{network}-{pool_short_id}
In legacy mode: uses legacy.lease.name or defaults to {fullname}-leader
*/}}
{{- define "cardano-node.leaseName" -}}
{{- if .Values.forgeManager.multiTenant.enabled -}}
{{- $network := .Values.cardanoNode.network -}}
{{- $poolShort := include "cardano-node.poolShortId" . -}}
{{- if and $network $poolShort -}}
{{- printf "cardano-leader-%s-%s" $network $poolShort | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-leader" (include "cardano-node.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- else if .Values.forgeManager.legacy.lease.name -}}
{{- .Values.forgeManager.legacy.lease.name -}}
{{- else -}}
{{- printf "%s-leader" (include "cardano-node.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{/*
Generate CardanoLeader CR name
In multi-tenant mode: cardano-leader-{network}-{pool_short_id}
In legacy mode: uses legacy.crd.cardanoLeader.name or defaults to {fullname}-leader
*/}}
{{- define "cardano-node.cardanoLeaderName" -}}
{{- if .Values.forgeManager.multiTenant.enabled -}}
{{- $network := .Values.cardanoNode.network -}}
{{- $poolShort := include "cardano-node.poolShortId" . -}}
{{- if and $network $poolShort -}}
{{- printf "cardano-leader-%s-%s" $network $poolShort | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-leader" (include "cardano-node.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- else if .Values.forgeManager.legacy.crd.cardanoLeader.name -}}
{{- .Values.forgeManager.legacy.crd.cardanoLeader.name -}}
{{- else -}}
{{- printf "%s-leader" (include "cardano-node.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{/*
Generate CardanoForgeCluster CR name
Format: {network}-{pool_short_id}-{region}
Example: mainnet-pool1abc-us-east-1
*/}}
{{- define "cardano-node.cardanoForgeClusterName" -}}
{{- if .Values.forgeManager.clusterManagement.enabled -}}
{{- $network := .Values.cardanoNode.network -}}
{{- $poolShort := include "cardano-node.poolShortId" . -}}
{{- $region := .Values.forgeManager.clusterManagement.region -}}
{{- if and $network $poolShort $region -}}
{{- printf "%s-%s-%s" $network $poolShort $region | trunc 63 | trimSuffix "-" -}}
{{- else if .Values.forgeManager.legacy.crd.cardanoForgeCluster.name -}}
{{- .Values.forgeManager.legacy.crd.cardanoForgeCluster.name -}}
{{- else -}}
{{- printf "%s-forge-cluster" (include "cardano-node.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- else if .Values.forgeManager.legacy.crd.cardanoForgeCluster.name -}}
{{- .Values.forgeManager.legacy.crd.cardanoForgeCluster.name -}}
{{- else -}}
{{- printf "%s-forge-cluster" (include "cardano-node.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{/*
Check if forge manager should be enabled
*/}}
{{- define "cardano-node.forgeManagerEnabled" -}}
{{- if and .Values.cardanoNode.blockProducer .Values.forgeManager.enabled -}}
true
{{- else -}}
false
{{- end -}}
{{- end }}

{{/*
Check if cluster management should be enabled
Cluster management requires forge manager to be enabled
*/}}
{{- define "cardano-node.clusterManagementEnabled" -}}
{{- if and (eq (include "cardano-node.forgeManagerEnabled" .) "true") .Values.forgeManager.clusterManagement.enabled -}}
true
{{- else -}}
false
{{- end -}}
{{- end }}

{{/*
Check if multi-tenant mode is enabled
Multi-tenant requires forge manager and pool ID
*/}}
{{- define "cardano-node.multiTenantEnabled" -}}
{{- if and (eq (include "cardano-node.forgeManagerEnabled" .) "true") .Values.forgeManager.multiTenant.enabled .Values.forgeManager.multiTenant.pool.id -}}
true
{{- else -}}
false
{{- end -}}
{{- end }}

{{/*
Generate network magic with validation
*/}}
{{- define "cardano-node.networkMagic" -}}
{{- $network := .Values.cardanoNode.network -}}
{{- $magic := .Values.cardanoNode.magic -}}
{{- if eq $network "mainnet" -}}
764824073
{{- else if eq $network "preprod" -}}
1
{{- else if eq $network "preview" -}}
2
{{- else -}}
{{- $magic -}}
{{- end -}}
{{- end }}

{{/*
Generate Byron genesis URL based on network
*/}}
{{- define "cardano-node.byronGenesisUrl" -}}
{{- $network := .Values.cardanoNode.network -}}
{{- if eq $network "mainnet" -}}
https://book.world.dev.cardano.org/environments/mainnet/byron-genesis.json
{{- else if eq $network "preprod" -}}
https://book.world.dev.cardano.org/environments/preprod/byron-genesis.json
{{- else if eq $network "preview" -}}
https://book.world.dev.cardano.org/environments/preview/byron-genesis.json
{{- else -}}
{{- "" -}}
{{- end -}}
{{- end }}

{{/*
Common annotations
*/}}
{{- define "cardano-node.annotations" -}}
{{- with .Values.global.commonAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
PVC name - either existing claim or generated name.
Takes a parameter: "ledger" or "socket"
*/}}
{{- define "cardano-node.pvcName" -}}
{{- $which := . -}}  {{/* parameter: "ledger" or "socket" */}}
{{- $p := index .Values.persistence $which -}}
{{- if $p.existingClaim -}}
{{- $p.existingClaim -}}
{{- else -}}
{{- printf "%s-%s" (include "cardano-node.fullname" $) $which -}}
{{- end -}}
{{- end }}

{{/*
Forge manager service name
*/}}
{{- define "cardano-node.forgeManagerServiceName" -}}
{{- printf "%s-forge-metrics" (include "cardano-node.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Validate multi-tenant configuration
*/}}
{{- define "cardano-node.validateMultiTenant" -}}
{{- if eq (include "cardano-node.multiTenantEnabled" .) "true" -}}
{{- if not .Values.cardanoNode.network -}}
{{- fail "Multi-tenant mode requires cardanoNode.network to be set" -}}
{{- end -}}
{{- if not .Values.forgeManager.multiTenant.pool.id -}}
{{- fail "Multi-tenant mode requires forgeManager.multiTenant.pool.id to be set" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Validate cluster management configuration
*/}}
{{- define "cardano-node.validateClusterManagement" -}}
{{- if eq (include "cardano-node.clusterManagementEnabled" .) "true" -}}
{{- if not .Values.forgeManager.clusterManagement.region -}}
{{- fail "Cluster management requires forgeManager.clusterManagement.region to be set" -}}
{{- end -}}
{{- if not .Values.cardanoNode.network -}}
{{- fail "Cluster management requires cardanoNode.network to be set" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Generate pool metadata for CRD
*/}}
{{- define "cardano-node.poolMetadata" -}}
id: {{ .Values.forgeManager.multiTenant.pool.id | quote }}
{{- if .Values.forgeManager.multiTenant.pool.idHex }}
idHex: {{ .Values.forgeManager.multiTenant.pool.idHex | quote }}
{{- end }}
{{- if .Values.forgeManager.multiTenant.pool.name }}
name: {{ .Values.forgeManager.multiTenant.pool.name | quote }}
{{- end }}
{{- if .Values.forgeManager.multiTenant.pool.ticker }}
ticker: {{ .Values.forgeManager.multiTenant.pool.ticker | quote }}
{{- end }}
{{- end }}
{{/*
Return "true" if either ledger or socket PVC template should be created.
Used to decide whether to emit the volumeClaimTemplates: root key.
*/}}
{{- define "cardano-node.requiresPVCs" -}}
{{- $ledger := .Values.persistence.ledger -}}
{{- $socket := .Values.persistence.socket -}}

{{- $needLedger := and $ledger.enabled (not $ledger.existingClaim) -}}
{{- $needSocket := and $socket.enabled (not $socket.existingClaim) -}}

{{- if or $needLedger $needSocket }}true{{ else }}false{{ end }}
{{- end }}

{{/*
Generate the list items for volumeClaimTemplates.
This helper does NOT emit the volumeClaimTemplates: key itself.
Indentation is controlled by callers via nindent.
*/}}
{{- define "cardano-node.volumeClaimTemplates" -}}
{{- $ledger := .Values.persistence.ledger -}}
{{- $socket := .Values.persistence.socket -}}

{{- $needLedger := and $ledger.enabled (not $ledger.existingClaim) -}}
{{- $needSocket := and $socket.enabled (not $socket.existingClaim) -}}

{{- if $needLedger }}
- metadata:
    name: cardano-data
    labels:
      {{- include "cardano-node.labels" . | nindent 6 }}
    {{- with $ledger.annotations }}
    annotations:
      {{- toYaml . | nindent 6 }}
    {{- end }}
  spec:
    accessModes:
      - {{ $ledger.accessMode | quote }}
    {{- if $ledger.storageClass }}
    {{- if (eq "-" $ledger.storageClass) }}
    storageClassName: ""
    {{- else }}
    storageClassName: {{ $ledger.storageClass | quote }}
    {{- end }}
    {{- end }}
    resources:
      requests:
        storage: {{ $ledger.size | quote }}
{{- end }}

{{- if $needSocket }}
- metadata:
    name: socket-dir
    labels:
      {{- include "cardano-node.labels" . | nindent 6 }}
    {{- with $socket.annotations }}
    annotations:
      {{- toYaml . | nindent 6 }}
    {{- end }}
  spec:
    accessModes:
      - {{ $socket.accessMode | quote }}
    {{- if $socket.storageClass }}
    {{- if (eq "-" $socket.storageClass) }}
    storageClassName: ""
    {{- else }}
    storageClassName: {{ $socket.storageClass | quote }}
    {{- end }}
    {{- end }}
    resources:
      requests:
        storage: {{ $socket.size | quote }}
{{- end }}
{{- end }}

{{/*
Helper templates for the litellm-mcp chart.
Resource names, labels and selectors are fixed (not derived from the release
name) on purpose: the Cloudflare tunnel routes to this exact Service name, and
changing a selector or a pod-template label would restart the console.
*/}}

{{- define "litellmMcp.ns" -}}
{{ .Values.namespace.name }}
{{- end -}}

{{/* Shared label on every object. Kept as `woow-litellm` (not -mcp): it is the
label the live objects carry, and changing a Deployment label is a no-op that
still shows up as drift. */}}
{{- define "litellmMcp.partOf" -}}
app.kubernetes.io/part-of: woow-litellm
{{- end -}}

{{/* `annotations:` block with the keep policy, or nothing. */}}
{{- define "litellmMcp.keepAnnotations" -}}
{{- if .Values.keepOnUninstall -}}
annotations:
  helm.sh/resource-policy: keep
{{- end -}}
{{- end -}}

{{/* storageClassName: the component override or the global default. */}}
{{- define "litellmMcp.storageClass" -}}
{{ default .Values.storageClassName .Values.admin.storage.className }}
{{- end -}}

{{/* Service DNS name of the console, for tests and NOTES. */}}
{{- define "litellmMcp.adminUrl" -}}
http://litellm-mcp-admin.{{ .Values.namespace.name }}.svc.cluster.local:8080
{{- end -}}

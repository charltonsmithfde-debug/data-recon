#!/usr/bin/env bash
# Shared helpers for the scripts/blocked/ runbook. Source it; do not execute it.
#
# Everything in this directory is a step the agent cannot run: each one is outward-facing,
# takes a live service down, reads a credential, or needs an authorisation decision. They are
# written to be run by a human, in order, from Git Bash on the workstation.

# shellcheck shell=bash

PROJECT_ID="${PROJECT_ID:-myanalyticsproduct}"
PROJECT_NUMBER="${PROJECT_NUMBER:-886154918734}"
REGION="${REGION:-europe-west1}"
ZONE="${ZONE:-europe-west1-b}"

SQL_VM="${SQL_VM:-scbi-cube-sql}"
SQL_PORT="${SQL_PORT:-5432}"
CUBE_SERVICE="${CUBE_SERVICE:-scbi-cube}"
METABASE_SERVICE="${METABASE_SERVICE:-scbi-metabase}"
THIN_WEB_SERVICE="${THIN_WEB_SERVICE:-scbi-thin-web}"
CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-scbi-ducklake-catalog}"
GCS_BUCKET="${DUCKLAKE_GCS_BUCKET:-scbi-ducklake-myanalyticsproduct}"
COMPUTE_SA="${COMPUTE_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"

# Where this runbook keeps things that must not go into the repo: the exported CA bundle, the
# probe's credential file, the rotation's transcript. Created 0700 on first use.
STATE_DIR="${SCBI_RUNBOOK_STATE:-${HOME}/.scbi-runbook}"

# ──────────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────────

if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

heading() { printf '\n%s== %s ==%s\n' "${C_BOLD}${C_BLUE}" "$1" "${C_RESET}"; }
ok()      { printf '  %sOK%s    %s\n' "${C_GREEN}" "${C_RESET}" "$1"; }
warn()    { printf '  %sWARN%s  %s\n' "${C_YELLOW}" "${C_RESET}" "$1"; }
bad()     { printf '  %sFAIL%s  %s\n' "${C_RED}" "${C_RESET}" "$1"; }
info()    { printf '  %s%s%s\n' "${C_DIM}" "$1" "${C_RESET}"; }
die()     { printf '\n%sABORT:%s %s\n\n' "${C_RED}${C_BOLD}" "${C_RESET}" "$1" >&2; exit 1; }

# ──────────────────────────────────────────────────────────────────────────────
# Zscaler TLS interception
# ──────────────────────────────────────────────────────────────────────────────
#
# This workstation sits behind Zscaler, which re-signs TLS. gcloud validates against its own
# bundled CA store, which has no Zscaler root; the Windows certificate store does. Every gcloud
# call that opens an IAP tunnel or an SSH session therefore fails with CERTIFICATE_VERIFY_FAILED
# until CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE points at a PEM exported from the Windows stores.
#
# Plain API calls (`gcloud run services list`, and so on) go through a different path and work
# without it, which is why this looked intermittent for two sessions.

require_ca_bundle() {
  local bundle="${CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE:-${STATE_DIR}/win-ca-bundle.pem}"
  if [ ! -s "${bundle}" ]; then
    die "No CA bundle at ${bundle}.
       Run 00_export_ca_bundle.ps1 from PowerShell first:
         powershell -ExecutionPolicy Bypass -File scripts/blocked/00_export_ca_bundle.ps1"
  fi
  export CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE="${bundle}"
  info "CA bundle: ${bundle} ($(grep -c 'BEGIN CERTIFICATE' "${bundle}") certificates)"
}

# ──────────────────────────────────────────────────────────────────────────────
# Guards
# ──────────────────────────────────────────────────────────────────────────────

require_state_dir() {
  mkdir -p "${STATE_DIR}"
  chmod 700 "${STATE_DIR}" 2>/dev/null || true
}

require_gcloud() {
  command -v gcloud >/dev/null 2>&1 || die "gcloud is not on PATH."
  local account
  account="$(gcloud config get-value account 2>/dev/null)"
  [ -n "${account}" ] && [ "${account}" != "(unset)" ] || die "gcloud is not authenticated. Run: gcloud auth login"
  gcloud config set project "${PROJECT_ID}" >/dev/null 2>&1
  info "gcloud: ${account} / ${PROJECT_ID} / ${REGION}"
}

# Anything that changes a live service asks first. --yes skips the prompt for unattended runs;
# nothing here is destructive enough to need a second confirmation, but nothing is reversible
# for free either.
confirm() {
  local prompt="$1"
  if [ "${ASSUME_YES:-0}" = "1" ]; then
    info "(--yes) ${prompt}"
    return 0
  fi
  printf '\n%s%s%s\n' "${C_BOLD}${C_YELLOW}" "${prompt}" "${C_RESET}"
  printf '  Type %sproceed%s to continue: ' "${C_BOLD}" "${C_RESET}"
  local reply
  read -r reply
  [ "${reply}" = "proceed" ] || die "Not confirmed."
}

parse_common_flags() {
  ASSUME_YES=0
  DRY_RUN=0
  REMAINING_ARGS=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes|-y)     ASSUME_YES=1 ;;
      --dry-run|-n) DRY_RUN=1 ;;
      *)            REMAINING_ARGS+=("$1") ;;
    esac
    shift
  done
  export ASSUME_YES DRY_RUN
}

# Echo the command, then run it -- unless --dry-run, in which case only echo. Secrets never
# reach a command line in this runbook, so echoing is safe by construction.
run() {
  printf '  %s$ %s%s\n' "${C_DIM}" "$*" "${C_RESET}"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    return 0
  fi
  "$@"
}

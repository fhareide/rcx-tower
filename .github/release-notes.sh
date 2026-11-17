#!/bin/sh
# The release note of one version: its "## <version>" section of CHANGELOG.md, without
# the heading, trimmed of blank lines at both ends. Prints nothing when there is none.
#   sh .github/release-notes.sh 0.10.0
awk -v v="$1" '
  /^## / { if (p) exit; p = ($2 == v); next }
  p { lines[++n] = $0 }
  END {
    s = 1; while (s <= n && lines[s] ~ /^[[:space:]]*$/) s++
    e = n; while (e >= s && lines[e] ~ /^[[:space:]]*$/) e--
    for (i = s; i <= e; i++) print lines[i]
  }' "$(dirname "$0")/../CHANGELOG.md"

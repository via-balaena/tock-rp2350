#!/bin/sh
# Licensed under the Apache License, Version 2.0 or the MIT License.
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright Jon Hillesheim 2026.
#
# Tock commit message gauge.
#
# .github/CONTRIBUTING.md:125-133 is a numbered list; item 3 is "Wrap all other
# lines at 72 columns", and the subject limit is 50. Written 2026-09-12 after
# the rule was broken three times in one session by someone who had it quoted
# in front of them, then broken a fourth time and caught by this script.
#
# Two modes, because a git hook cannot survive a clone and a gate can:
#
#   commit-msg-check.sh --file <path>     one message, for the commit-msg hook
#   commit-msg-check.sh --range <range>   every commit in a range, for gates.sh
#
# Exit 0 clean, 1 a message is out of spec, 2 the check could not run.
#
# Exempt, deliberately: merge/revert/fixup subjects, comment lines, trailers,
# bare URLs, and lines indented four spaces, which is CONTRIBUTING's own form
# for quoted material.

SUBJECT_MAX=50
BODY_MAX=72

check_one() {
    # $1 = path to a message file, $2 = label for reporting
    msg="$1"; label="$2"; n=0; bad=0

    while IFS= read -r line || [ -n "$line" ]; do
        n=$((n + 1))
        case "$line" in '#'*) continue ;; esac

        if [ "$n" -eq 1 ]; then
            case "$line" in
                Merge\ *|Revert\ *|fixup!\ *|squash!\ *) return 0 ;;
            esac
            len=$(printf '%s' "$line" | wc -c | tr -d ' ')
            if [ "$len" -gt "$SUBJECT_MAX" ]; then
                echo "  $label: subject is $len columns, limit is $SUBJECT_MAX" >&2
                echo "    $line" >&2
                bad=1
            fi
            case "$line" in
                *.) echo "  $label: subject ends in a period" >&2; bad=1 ;;
            esac
            continue
        fi

        case "$line" in
            '    '*) continue ;;                               # quoted material
            *://*) continue ;;                                 # bare URL
            Co-Authored-By:*|Signed-off-by:*|Assisted-by:*) continue ;;
            Fixes\ *|Closes\ *) continue ;;
        esac

        len=$(printf '%s' "$line" | wc -c | tr -d ' ')
        if [ "$len" -gt "$BODY_MAX" ]; then
            echo "  $label: line $n is $len columns, limit is $BODY_MAX" >&2
            echo "    $line" >&2
            bad=1
        fi
    done < "$msg"

    return $bad
}

mode=""; arg=""
while [ $# -gt 0 ]; do
    case "$1" in
        --file)  mode=file;  arg="$2"; shift 2 ;;
        --range) mode=range; arg="$2"; shift 2 ;;
        *) echo "usage: commit-msg-check.sh --file <path> | --range <range>" >&2
           exit 2 ;;
    esac
done

case "$mode" in
    file)
        [ -r "$arg" ] || { echo "cannot read $arg" >&2; exit 2; }
        if check_one "$arg" "commit-msg"; then exit 0; fi
        echo "" >&2
        echo "Rewrap and commit again. CONTRIBUTING.md:125-133, not a preference." >&2
        exit 1
        ;;
    range)
        git rev-parse --verify --quiet "${arg%%..*}" >/dev/null 2>&1 || {
            echo "  range does not resolve: $arg" >&2; exit 2; }
        shas=$(git rev-list "$arg" 2>/dev/null) || {
            echo "  could not list commits in $arg" >&2; exit 2; }
        [ -z "$shas" ] && { echo "  no commits in $arg"; exit 0; }
        tmp=$(mktemp); rc=0; n=0
        for sha in $shas; do
            n=$((n + 1))
            git log -1 --format=%B "$sha" > "$tmp"
            check_one "$tmp" "$(git log -1 --format=%h "$sha")" || rc=1
        done
        rm -f "$tmp"
        [ "$rc" -eq 0 ] && echo "  $n commit message(s) within spec"
        exit $rc
        ;;
    *)
        echo "usage: commit-msg-check.sh --file <path> | --range <range>" >&2
        exit 2
        ;;
esac

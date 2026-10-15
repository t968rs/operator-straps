#!/usr/bin/env bash
# Bisection script to find which test creates unwanted files/state
# Usage: bash find-polluter.sh <file_or_dir_to_check> <test_pattern> [test command...]
# Example: bash find-polluter.sh 'packages/core/.git' 'src/**/*.test.ts'
# Example: bash find-polluter.sh '.tmp_output' 'tests/**/test_*.py' python -m pytest -q
# The test command (default: npm test) runs once per test file, with the file as its last argument.
# Exit codes: 0 no polluter found (all tests clean), 1 polluter found,
# 2 could not bisect (unusable input, no test files match, pollution target
# already present, or test command missing).

set -e

if [ $# -lt 2 ]; then
  echo "Usage: $0 <file_to_check> <test_pattern> [test command...]"
  echo "Example: $0 'packages/core/.git' 'src/**/*.test.ts'"
  echo "Example: $0 '.tmp_output' 'tests/**/test_*.py' python -m pytest -q"
  exit 2
fi

POLLUTION_CHECK="$1"
TEST_PATTERN="$2"
shift 2
if [ $# -gt 0 ]; then
  TEST_CMD=("$@")
else
  TEST_CMD=(npm test)
fi

echo "🔍 Searching for test that creates: $POLLUTION_CHECK"
echo "Test pattern: $TEST_PATTERN"
echo "Test command: ${TEST_CMD[*]} <file>"
echo ""

# Get list of test files (find . emits ./-prefixed paths, so accept the
# pattern written with or without a leading ./)
TEST_PATTERN="${TEST_PATTERN#./}"
# find -path can't match '**/' against zero directory levels, so a pattern
# like src/**/*.test.ts would skip src/top.test.ts; also try the pattern
# with '**/' collapsed to cover files directly under the base directory.
TEST_FILES=$(find . \( -path "./$TEST_PATTERN" -o -path "./${TEST_PATTERN//\*\*\//}" \) | sort -u)
if [ -z "$TEST_FILES" ]; then
  TOTAL=0
else
  TOTAL=$(printf '%s\n' "$TEST_FILES" | wc -l | tr -d ' ')
fi

echo "Found $TOTAL test files"
echo ""

# Zero matches would run no test, so a clean verdict would prove nothing
if [ "$TOTAL" -eq 0 ]; then
  echo "No test files match: $TEST_PATTERN"
  echo "Check the pattern is relative to this directory (the project root)."
  exit 2
fi

# Every test would be skipped against a target that is already there, so nothing could be bisected
if [ -e "$POLLUTION_CHECK" ]; then
  echo "Pollution target already exists before any test ran: $POLLUTION_CHECK"
  echo "Remove it, or run from a clean disposable workspace where it is absent, then rerun."
  exit 2
fi

COUNT=0
FAILED=0
# One path per line, read whole: names with spaces or glob characters stay intact.
while IFS= read -r -u 3 TEST_FILE; do
  [ -n "$TEST_FILE" ] || continue
  COUNT=$((COUNT + 1))

  echo "[$COUNT/$TOTAL] Testing: $TEST_FILE"

  # Run the test; a failing test is expected, a missing runner is not
  STATUS=0
  "${TEST_CMD[@]}" "$TEST_FILE" < /dev/null > /dev/null 2>&1 || STATUS=$?
  if [ "$STATUS" -eq 126 ] || [ "$STATUS" -eq 127 ]; then
    echo "Test command could not run (exit $STATUS): ${TEST_CMD[*]}"
    exit 2
  fi
  [ "$STATUS" -eq 0 ] || FAILED=$((FAILED + 1))

  # Check if pollution appeared
  if [ -e "$POLLUTION_CHECK" ]; then
    echo ""
    echo "🎯 FOUND POLLUTER!"
    echo "   Test: $TEST_FILE"
    echo "   Created: $POLLUTION_CHECK"
    echo ""
    echo "Pollution details:"
    ls -la "$POLLUTION_CHECK"
    echo ""
    echo "To investigate:"
    echo "  ${TEST_CMD[*]} \"$TEST_FILE\"    # Run just this test"
    echo "  cat \"$TEST_FILE\"         # Review test code"
    exit 1
  fi
done 3<<< "$TEST_FILES"

echo ""
if [ "$FAILED" -gt 0 ]; then
  echo "Note: $FAILED of $COUNT test files exited non-zero."
fi
echo "✅ No polluter found - all tests clean!"
exit 0

#!/usr/bin/env bash

PAYLOAD=$(cat)
TOOL_NAME=$(echo "$PAYLOAD" | jq -r '.tool_name')
COMMAND=$(echo "$PAYLOAD" | jq -r '.tool_input.command // ""')

if [ "$TOOL_NAME" != "Bash" ]; then
    echo '{"decision": "allow"}'
    exit 0
fi

# 1. gh pr merge ...
if echo "$COMMAND" | grep -qE '^gh pr merge\b'; then
    echo '{"decision": "deny", "reason": "PreToolUse hook blocks gh pr merge"}'
    exit 1
fi

# 2. gh api with PUT/POST to a path matching */pulls/*/merge
if echo "$COMMAND" | grep -qE '^gh api\b'; then
    if echo "$COMMAND" | grep -qEi -- '-(X|-method)\s*(PUT|POST)'; then
        if echo "$COMMAND" | grep -qE '/pulls/[0-9]+/merge'; then
            echo '{"decision": "deny", "reason": "PreToolUse hook blocks gh api PUT/POST to /merge endpoints"}'
            exit 1
        fi
    fi
fi

# 3. curl to the same REST path
if echo "$COMMAND" | grep -qE '^curl\b'; then
    if echo "$COMMAND" | grep -qEi -- '-(X|-request)\s*(PUT|POST)'; then
        if echo "$COMMAND" | grep -qE '/pulls/[0-9]+/merge'; then
            echo '{"decision": "deny", "reason": "PreToolUse hook blocks curl PUT/POST to /merge endpoints"}'
            exit 1
        fi
    fi
fi

echo '{"decision": "allow"}'
exit 0

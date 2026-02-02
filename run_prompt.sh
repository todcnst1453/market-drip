#!/bin/bash

# --- 1. Validation First ---
# Check arguments before doing anything to the Git tree
if [ -z "$1" ]; then
    echo "Usage: ./run_prompt.sh <prompt_file_name>"
    echo "Example: ./run_prompt.sh feature_request.md"
    exit 1
fi

PROMPT_FILE="prompts/$1"
if [ ! -f "$PROMPT_FILE" ]; then
    echo "Error: Prompt file '$PROMPT_FILE' not found in prompts/ directory."
    exit 1
fi

# --- 2. Environment Setup ---
export GOOGLE_CLOUD_PROJECT=$(gcloud config get-value project)
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_LOCATION="us-central1"
export GOOGLE_CLOUD_QUOTA_PROJECT=$GOOGLE_CLOUD_PROJECT

# --- 3. Git Safeguard ---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PROMPT_BASE=$(basename "$1" .md)
SAFE_BRANCH="ai-task-$PROMPT_BASE-$TIMESTAMP"

echo "🛡️  Checking git status..."
if ! git diff-index --quiet HEAD --; then
    echo "⚠️  Warning: Uncommitted changes detected. Stashing them..."
    git stash
fi

echo "🌿 Creating safety branch: $SAFE_BRANCH"
git checkout -b "$SAFE_BRANCH"

# --- 4. Execution ---
echo "------------------------------------------------"
echo "🤖 Gemini Agent is processing: $1"
echo "------------------------------------------------"
# Combine GEMINI.md and the PROMPT_FILE to feed into gemini
# We use cat to pipe both into gemini, using -p (or --prompt) to trigger non-interactive mode.
cat GEMINI.md "$PROMPT_FILE" | gemini \
  -m "auto" \
  --include-directories="." \
  --approval-mode="yolo" \
  -p "-"

# --- 5. Post-Execution ---
echo "------------------------------------------------"
echo "✅ Task complete. Review changes on branch: $SAFE_BRANCH"
echo "To keep changes:  git checkout main && git merge $SAFE_BRANCH"
echo "To discard:       git checkout main && git branch -D $SAFE_BRANCH"
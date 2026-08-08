#!/usr/bin/env bash
set -e

# Feature Lifecycle Orchestration Loop
# Model enforced: gemini-2.5-flash (or gemini-3.6-flash-low / flash model via opencode flag)

FEATURES=("F2-similarity-engine" "F3-resolution-engine" "F4-reply-drafting" "F5-two-lane-dashboard" "F6-human-override-controls" "F7-live-ticket-simulation")
MODEL="google/gemini-2.5-flash"

echo "=========================================================="
echo "Starting Lifecycle Loop for Support Ticket Manager Features"
echo "=========================================================="

for FEATURE in "${FEATURES[@]}"; do
    SESSION_NAME="feat-${FEATURE}"
    echo ""
    echo "----------------------------------------------------------"
    echo "Processing Feature: ${FEATURE}"
    echo "Session Name: ${SESSION_NAME}"
    echo "----------------------------------------------------------"

    # Step 1: /generate-spec
    echo "[1/6] Generating Spec for ${FEATURE}..."
    opencode run --model "${MODEL}" --session "${SESSION_NAME}" --title "${SESSION_NAME}" "/generate-spec ${FEATURE}"

    # Step 2: /generate-tech-spec
    echo "[2/6] Generating Tech Spec for ${FEATURE}..."
    opencode run --model "${MODEL}" --session "${SESSION_NAME}" --title "${SESSION_NAME}" "/generate-tech-spec ${FEATURE}"

    # Step 3: /generate-tests
    echo "[3/6] Generating Tests for ${FEATURE}..."
    opencode run --model "${MODEL}" --session "${SESSION_NAME}" --title "${SESSION_NAME}" "/generate-tests ${FEATURE}"

    # Step 4: /implement-feature
    echo "[4/6] Implementing Feature ${FEATURE}..."
    opencode run --model "${MODEL}" --session "${SESSION_NAME}" --title "${SESSION_NAME}" "/implement-feature ${FEATURE}"

    # Step 5: /validate-feature (and run pytest using uv environment)
    echo "[5/6] Validating Feature ${FEATURE}..."
    PYTHONPATH=backend uv run pytest
    opencode run --model "${MODEL}" --session "${SESSION_NAME}" --title "${SESSION_NAME}" "/validate-feature ${FEATURE}"

    # Step 6: /generate-summary
    echo "[6/6] Generating Summary for ${FEATURE}..."
    opencode run --model "${MODEL}" --session "${SESSION_NAME}" --title "${SESSION_NAME}" "/generate-summary ${FEATURE}"

    # Commit changes for feature completion
    echo "Committing completed feature: ${FEATURE}..."
    git add .
    git commit -m "Completed ${FEATURE}" || echo "No changes to commit for ${FEATURE}"

    echo "Successfully completed lifecycle for ${FEATURE}"
done

echo "=========================================================="
echo "All feature lifecycles completed successfully!"
echo "=========================================================="

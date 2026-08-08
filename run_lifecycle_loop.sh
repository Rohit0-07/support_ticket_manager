#!/bin/bash

# Array of features from INDEX.md
FEATURES=(
    "data-ingestion"
    "similarity-engine"
    "resolution-engine"
    "reply-drafting"
    "two-lane-dashboard"
)

echo "Starting Feature Lifecycle Loop..."

AGY_CMD="agy --model gemini-3.6-flash-low --effort low --dangerously-skip-permissions --print-timeout 30m -p"

for feature in "${FEATURES[@]}"; do
    echo "========================================"
    echo "Starting lifecycle for feature: $feature"
    echo "========================================"
    
    # Locate the feature directory (could be $feature or F1-$feature etc.)
    FEAT_DIR="features/$feature"
    if [ ! -d "$FEAT_DIR" ]; then
        # Try to find it if it has a prefix like F1-
        MATCHING_DIR=$(ls -d features/*-$feature 2>/dev/null | head -n 1)
        if [ -n "$MATCHING_DIR" ]; then
            FEAT_DIR="$MATCHING_DIR"
        fi
    fi

    # Check if completely done
    if [ -f "$FEAT_DIR/3_summary.md" ]; then
        echo "Feature $feature is already fully complete (3_summary.md exists). Skipping."
        continue
    fi

    # 1. Spec
    if [ ! -f "$FEAT_DIR/1_spec.md" ]; then
        echo "Running /generate-spec $feature..."
        $AGY_CMD "/generate-spec $feature"
    else
        echo "Skipping /generate-spec (1_spec.md exists)"
    fi

    # Update FEAT_DIR in case it was just created
    if [ ! -d "$FEAT_DIR" ]; then
        MATCHING_DIR=$(ls -d features/*-$feature 2>/dev/null | head -n 1)
        if [ -n "$MATCHING_DIR" ]; then
            FEAT_DIR="$MATCHING_DIR"
        fi
        # Default fallback
        if [ ! -d "$FEAT_DIR" ]; then
            FEAT_DIR="features/$feature"
        fi
    fi

    # 2. Tech Spec
    if [ ! -f "$FEAT_DIR/2_tech_spec.md" ]; then
        echo "Running /generate-tech-spec $feature..."
        $AGY_CMD "/generate-tech-spec $feature"
    else
        echo "Skipping /generate-tech-spec (2_tech_spec.md exists)"
    fi

    # 3. Tests
    TEST_FEAT_NAME="${feature//-/_}"
    if [ ! -f "$FEAT_DIR/tests/test_${TEST_FEAT_NAME}.py" ]; then
        echo "Running /generate-tests $feature..."
        $AGY_CMD "/generate-tests $feature"
    else
        echo "Skipping /generate-tests (tests/test_${TEST_FEAT_NAME}.py exists)"
    fi

    # 4. Implement Feature
    echo "Running /implement-feature $feature..."
    $AGY_CMD "/implement-feature $feature"

    # 5. Validate
    echo "Running /validate-feature $feature..."
    $AGY_CMD "/validate-feature $feature"

    # 6. Summary
    if [ ! -f "$FEAT_DIR/3_summary.md" ]; then
        echo "Running /generate-summary $feature..."
        $AGY_CMD "/generate-summary $feature"
    fi

    echo "Committing changes for $feature..."
    git add .
    git commit -m "Complete feature: $feature" || echo "No changes to commit."

    echo "Agy session completed for $feature."
done

echo "All features processed!"

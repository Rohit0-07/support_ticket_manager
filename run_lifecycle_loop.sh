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

# agy command with --add-dir . so it knows the workspace context
AGY_CMD="agy --model gemini-3.6-flash-low --effort low --dangerously-skip-permissions --print-timeout 30m --add-dir . -p"

# Helper to run harness command with injected rules
run_harness_cmd() {
    local cmd_name=$1
    local target_feature=$2
    local cmd_file=".opencode/commands/${cmd_name}.md"
    
    echo "Running /$cmd_name $target_feature..."
    
    if [ -f "$cmd_file" ]; then
        # Read the command markdown
        local cmd_content=$(cat "$cmd_file")
        
        # Build a robust prompt that forces the LLM to follow the slash command rules
        local full_prompt="You are executing the custom project harness command: /$cmd_name $target_feature

Here are the strict instructions, isolation rules, and output targets for this command:
=================================================
$cmd_content
=================================================

Please perform the task for the feature: $target_feature now.
Crucial: You must write the output files to the actual workspace directory exactly as specified in the Output Target section. Do NOT hallucinate paths or write to a scratch directory."

        # Execute
        $AGY_CMD "$full_prompt"
    else
        echo "Error: Command definition $cmd_file not found. Running generically."
        $AGY_CMD "/$cmd_name $target_feature"
    fi
}

for feature in "${FEATURES[@]}"; do
    echo "========================================"
    echo "Starting lifecycle for feature: $feature"
    echo "========================================"
    
    # Locate the feature directory
    FEAT_DIR="features/$feature"
    if [ ! -d "$FEAT_DIR" ]; then
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
        run_harness_cmd "generate-spec" "$feature"
    else
        echo "Skipping /generate-spec (1_spec.md exists)"
    fi

    # Update FEAT_DIR in case it was just created
    if [ ! -d "$FEAT_DIR" ]; then
        MATCHING_DIR=$(ls -d features/*-$feature 2>/dev/null | head -n 1)
        if [ -n "$MATCHING_DIR" ]; then
            FEAT_DIR="$MATCHING_DIR"
        fi
        if [ ! -d "$FEAT_DIR" ]; then
            FEAT_DIR="features/$feature"
        fi
    fi

    # 2. Tech Spec
    if [ ! -f "$FEAT_DIR/2_tech_spec.md" ]; then
        run_harness_cmd "generate-tech-spec" "$feature"
    else
        echo "Skipping /generate-tech-spec (2_tech_spec.md exists)"
    fi

    # 3. Tests
    TEST_FEAT_NAME="${feature//-/_}"
    if [ ! -f "$FEAT_DIR/tests/test_${TEST_FEAT_NAME}.py" ]; then
        run_harness_cmd "generate-tests" "$feature"
    else
        echo "Skipping /generate-tests (tests/test_${TEST_FEAT_NAME}.py exists)"
    fi

    # 4. Implement Feature
    run_harness_cmd "implement-feature" "$feature"

    # 5. Validate
    run_harness_cmd "validate-feature" "$feature"

    # 6. Summary
    if [ ! -f "$FEAT_DIR/3_summary.md" ]; then
        run_harness_cmd "generate-summary" "$feature"
    fi

    echo "Committing changes for $feature..."
    git add .
    git commit -m "Complete feature: $feature" || echo "No changes to commit."

    echo "Agy session completed for $feature."
done

echo "All features processed!"

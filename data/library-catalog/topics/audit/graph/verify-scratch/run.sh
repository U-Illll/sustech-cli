#!/bin/bash
TOOL=/home/wzh/go/lib-catalog-data/topics/audit/graph/topic_graph.audited.py
export PYTHONPATH=/home/wzh/go/reasonix-scripts/lib-catalog
S=/home/wzh/go/lib-catalog-data/topics/audit/graph/verify-scratch
run(){ echo "### $*"; python3 "$TOOL" "$@" 2>&1 | head -25; echo "--- exit=${PIPESTATUS[0]}"; }

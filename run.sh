#!/usr/bin/env bash
set -euo pipefail

uv run uvicorn main:app --reload

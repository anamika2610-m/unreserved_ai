#!/bin/bash
# Chat summary cron job – runs daily at 11:20 AM
# Crontab: 20 11 * * * /path/to/infra/scripts/summary_cron.sh

# Set working directory to project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}/../../"

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Set environment variables (adjust path as needed)
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Call the API endpoint to trigger summary generation
# Use 127.0.0.1 to avoid IPv6 (::1) resolution issues; replace localhost if set in .env
API_URL="${API_URL:-http://127.0.0.1:8000}"
API_URL="${API_URL//localhost/127.0.0.1}"
ENDPOINT="${API_URL}/api/v1/admin/summaries/generate"

# Optional: file to record last run for GET /api/v1/admin/cron/status
CRON_LAST_RUN_FILE="${CRON_LAST_RUN_FILE:-/tmp/unreserved_summary_cron_last_run.txt}"

echo "$(date '+%Y-%m-%dT%H:%M:%S%z'): Starting summary generation cron job"
echo "Calling endpoint: ${ENDPOINT}"

# Preflight: check that the API is reachable before running the long summary job
if ! curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "${API_URL}/health" | grep -q 200; then
    echo "ERROR: API not reachable at ${API_URL}. Start the server with: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
    exit 1
fi

# Make the API call (long timeout: summary job can take minutes due to LLM calls)
response=$(curl -s -X POST "${ENDPOINT}?days_required=7" \
    -H "Content-Type: application/json" \
    --connect-timeout 15 \
    --max-time 600 \
    -w "\nHTTP_STATUS:%{http_code}")

# Extract HTTP status
http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)
body=$(echo "$response" | sed '/HTTP_STATUS/d')

# Status 000 = curl could not connect (server down, wrong host, or timeout)
if [ -z "$http_status" ] || [ "$http_status" = "000" ]; then
    echo "$(date '+%Y-%m-%dT%H:%M:%S%z'): ERROR - Could not reach API (status 000). Is the server running at ${API_URL}?"
    echo "  Check: curl -s -o /dev/null -w '%{http_code}' ${API_URL}/health"
    exit 1
fi

# Register last run with the API so GET /api/v1/admin/cron/status shows it (works when API and cron share same server)
LAST_RUN_AT=$(date '+%Y-%m-%dT%H:%M:%S%z')
curl -s -X POST "${API_URL}/api/v1/admin/cron/last-run" \
    -H "Content-Type: application/json" \
    -d "{\"last_run_at\": \"${LAST_RUN_AT}\", \"status\": \"${http_status}\"}" \
    > /dev/null || true

if [ "$http_status" = "200" ]; then
    echo "$(date '+%Y-%m-%dT%H:%M:%S%z'): Summary generation completed successfully"
    echo "Response: $body"
else
    echo "$(date '+%Y-%m-%dT%H:%M:%S%z'): ERROR - Summary generation failed with HTTP status $http_status"
    echo "Response: $body"
    exit 1
fi

echo "$(date '+%Y-%m-%dT%H:%M:%S%z'): Cron job completed"

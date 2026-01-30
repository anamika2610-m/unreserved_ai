#!/bin/bash
# Cron job script for generating listing summaries
# Run this script every night via cron: 0 2 * * * /path/to/summary_cron.sh

# Set working directory
cd "$(dirname "$0")/../../"

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Set environment variables (adjust path as needed)
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Call the API endpoint to trigger summary generation
# Adjust the URL and port as needed
API_URL="${API_URL:-http://localhost:8000}"
ENDPOINT="${API_URL}/api/v1/admin/summaries/generate"

echo "$(date): Starting summary generation cron job"
echo "Calling endpoint: ${ENDPOINT}"

# Make the API call
response=$(curl -s -X POST "${ENDPOINT}?days_required=7" \
    -H "Content-Type: application/json" \
    -w "\nHTTP_STATUS:%{http_code}")

# Extract HTTP status
http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)
body=$(echo "$response" | sed '/HTTP_STATUS/d')

if [ "$http_status" = "200" ]; then
    echo "$(date): Summary generation completed successfully"
    echo "Response: $body"
else
    echo "$(date): ERROR - Summary generation failed with status $http_status"
    echo "Response: $body"
    exit 1
fi

echo "$(date): Cron job completed"

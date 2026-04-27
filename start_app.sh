#!/bin/bash

# start_app.sh

echo -e "\033[0;36m==========================================\033[0m"
echo -e "\033[0;36m   CryptoInsight - Safe Start             \033[0m"
echo -e "\033[0;36m==========================================\033[0m"

# 1. Startup
echo -e "\n\033[1;33m[1/2] Starting services...\033[0m"
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
if [ $? -ne 0 ]; then
    echo -e "\033[0;31mError during startup. Exiting.\033[0m"
    exit 1
fi

# 2. Wait for API
echo -e "\n\033[1;33m[2/2] Waiting for API to be ready...\033[0m"
max_retries=30
retry_count=0
healthy=false

while [ $retry_count -lt $max_retries ]; do
    sleep 2
    if curl -s "http://localhost:8000/api/health" | grep -q "ok"; then
        healthy=true
        break
    fi
    echo -n "."
    retry_count=$((retry_count+1))
done

if [ "$healthy" = false ]; then
    echo -e "\n\033[0;31mAPI did not become ready in time. Please check logs.\033[0m"
    exit 1
fi
echo -e "\n\033[0;32mAPI is up and running!\033[0m"

echo -e "\033[0;36m==========================================\033[0m"
echo -e "\033[0;36m   App Started!                           \033[0m"
echo -e "\033[0;36m==========================================\033[0m"
echo -e "\033[0;32mFrontend:    http://localhost:3000\033[0m"
echo -e "\033[0;32mAPI Docs:    http://localhost:8000/docs\033[0m"
echo -e "\033[0;32mHealth Check: http://localhost:8000/api/health\033[0m"
echo -e "\033[0;36m==========================================\033[0m"

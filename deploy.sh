#!/bin/bash
# =====================================================================
# PolyFree Backend - Vollautomatisches Deployment auf Debian 13 VPS
# Einmal ausführen: chmod +x deploy.sh && sudo ./deploy.sh
# =====================================================================

set -euo pipefail

echo "🚀 PolyFree Backend Deployment gestartet..."
echo "=============================================="

# 1. System aktualisieren & Docker installieren
echo "📦 [1/8] System aktualisieren & Docker installieren..."
apt update && apt upgrade -y
apt install -y curl git ca-certificates gnupg lsb-release unzip

# Docker Repository
mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 2. Benutzer 'piepell' für Docker-Gruppe (falls nicht root)
if id "piepell" &>/dev/null; then
    usermod -aG docker piepell
    echo "✅ User 'piepell' zu docker-Gruppe hinzugefügt"
else
    echo "⚠️  User 'piepell' nicht gefunden – läuft als root weiter"
fi

# 3. Repository klonen (polyfree2)
echo "📥 [2/8] Repository klonen..."
cd /opt
rm -rf polyfree
git clone https://github.com/piepell/polyfree2.git polyfree
cd /opt/polyfree

# 4. .env Datei erstellen
echo "🔐 [3/8] .env Konfiguration erstellen..."
SECRET=$(openssl rand -hex 32)
cat > .env <<EOF
SECRET_KEY=$SECRET
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080
ADMIN_USERNAME=admin
ADMIN_PASSWORD=PolyFree2026!
POLYFREE_ENGINE_PATH=/opt/polyfree/bin/polyfree_pipeline
POLYFREE_LIB_PATH=/opt/polyfree/lib/libpolyfree_core.a
EOF

# 5. Docker Compose Build & Start
echo "🐳 [4/8] Docker Images bauen (CPU-Container + Caddy)..."
docker compose up -d --build photogrammetry-cpu caddy

# 6. Warten bis Container healthy
echo "⏳ [5/8] Warte auf Container-Start (30s)..."
sleep 30

# 7. Health Checks
echo "🏥 [6/8] Health Checks durchführen..."
for i in {1..10}; do
    if curl -sf http://localhost:8001/api/health > /dev/null; then
        echo "✅ FastAPI Health: OK"
        break
    fi
    echo "   Versuch $i/10..."
    sleep 3
done

echo "🔧 Engine Status prüfen..."
curl -sf http://localhost:8001/api/engine/status | jq . || echo "⚠️  Engine Status noch nicht bereit"

# 8. Caddy HTTPS Test (nach DNS-Auflösung)
echo "🌐 [7/8] Caddy HTTPS Test (polyfreeapp.duckdns.org)..."
echo "   Hinweis: Funktioniert erst nach DNS-Auflösung auf diese IP"
curl -sf https://polyfreeapp.duckdns.org/api/health 2>/dev/null && echo "✅ HTTPS Health: OK" || echo "ℹ️  HTTPS erst nach DNS-Propagation verfügbar"

# 9. Zusammenfassung
echo "📋 [8/8] Deployment Zusammenfassung"
echo "=============================================="
docker compose ps
echo ""
echo "🎉 DEPLOYMENT ABGESCHLOSSEN!"
echo ""
echo "📍 Lokale API (HTTP):     http://localhost:8001/api/"
echo "📍 Öffentliche API (HTTPS): https://polyfreeapp.duckdns.org/api/"
echo "📍 Swagger UI:            https://polyfreeapp.duckdns.org/docs"
echo "📍 Health:                https://polyfreeapp.duckdns.org/api/health"
echo "📍 Engine Status:         https://polyfreeapp.duckdns.org/api/engine/status"
echo ""
echo "🔑 Admin Login:           admin / PolyFree2026!"
echo "🔑 Token holen:           curl -X POST https://polyfreeapp.duckdns.org/api/auth/token -H 'Content-Type: application/json' -d '{\"username\":\"admin\",\"password\":\"PolyFree2026!\"}'"
echo ""
echo "📋 Logs anzeigen:         docker compose logs -f photogrammetry-cpu"
echo "📋 Caddy Logs:            docker compose logs -f caddy"
echo "📋 Neustart:              docker compose restart"
echo ""
echo "✅ Das Backend ist bereit für die App!"
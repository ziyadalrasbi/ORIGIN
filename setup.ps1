# PowerShell script for ORIGIN setup

Write-Host "ORIGIN Setup Script" -ForegroundColor Green
Write-Host ""

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from env.example..." -ForegroundColor Yellow
    Copy-Item "env.example" ".env"
    Write-Host "✓ .env created. Please review and update if needed." -ForegroundColor Green
}

# Start services
Write-Host "Starting Docker services..." -ForegroundColor Yellow
docker-compose up -d

Write-Host "Waiting for services to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Run migrations
Write-Host "Running database migrations..." -ForegroundColor Yellow
docker-compose exec -T api alembic upgrade head

# Seed data
Write-Host "Seeding initial data..." -ForegroundColor Yellow
docker-compose exec -T api python -m origin_api.cli seed

Write-Host ""
Write-Host "✓ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Services are running. Test with:" -ForegroundColor Cyan
Write-Host "  curl http://localhost:8000/health" -ForegroundColor White
Write-Host ""
Write-Host "View logs with: docker-compose logs -f" -ForegroundColor Cyan


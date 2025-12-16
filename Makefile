.PHONY: help up down logs migrate seed test clean

help:
	@echo "ORIGIN - Makefile Commands"
	@echo ""
	@echo "  make up          - Start all services"
	@echo "  make down        - Stop all services"
	@echo "  make logs        - View logs from all services"
	@echo "  make migrate     - Run database migrations"
	@echo "  make seed        - Seed initial data"
	@echo "  make test        - Run tests"
	@echo "  make clean       - Remove volumes and clean up"
	@echo "  make shell-api   - Open shell in API container"
	@echo "  make shell-db    - Open psql shell"

up:
	docker-compose up -d
	@echo "Services starting... Use 'make logs' to view logs"

down:
	docker-compose down

logs:
	docker-compose logs -f

migrate:
	docker-compose exec api alembic upgrade head

migrate-create:
	docker-compose exec api alembic revision --autogenerate -m "$(name)"

seed:
	docker-compose exec api python -m origin_api.cli seed

test:
	docker-compose exec api pytest tests/ -v

clean:
	docker-compose down -v
	@echo "Volumes removed. Run 'make up' to start fresh."

shell-api:
	docker-compose exec api /bin/bash

shell-db:
	docker-compose exec postgres psql -U origin origin


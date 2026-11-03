.PHONY: dev run test lint docker-build docker-up

dev:
	npx concurrently -n vite,server,camera "npm run dev --prefix apps/web" "python -m nodiq.api.server" "python apps/camera-agent/agent_server.py"

run:
	python -m nodiq.api.server

test:
	python -m pytest tests/ -q

lint:
	ruff check .

docker-build:
	docker build -f deploy/Dockerfile -t nodiq .

docker-up:
	docker compose -f deploy/docker-compose.yml up -d

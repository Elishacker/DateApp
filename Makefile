.PHONY: help install migrate seed run worker beat test lint boundaries clean

help:
	@echo "Zynora"
	@echo "  make install     Create the virtualenv and install dependencies"
	@echo "  make migrate     Apply database migrations"
	@echo "  make seed        Load demo data"
	@echo "  make run         Start the ASGI development server"
	@echo "  make worker      Start a Celery worker"
	@echo "  make beat        Start the Celery scheduler"
	@echo "  make test        Run the test suite"
	@echo "  make lint        Run ruff"
	@echo "  make boundaries  Verify service boundaries and icon usage"

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements/development.txt

migrate:
	.venv/bin/python manage.py makemigrations
	.venv/bin/python manage.py migrate

seed:
	.venv/bin/python manage.py seed_demo --users 30

run:
	.venv/bin/python manage.py runserver 0.0.0.0:8000

worker:
	.venv/bin/celery -A config worker -l info

beat:
	.venv/bin/celery -A config beat -l info

test:
	.venv/bin/python manage.py test apps tests -v 2

lint:
	.venv/bin/ruff check apps config

boundaries:
	.venv/bin/python manage.py check_boundaries
	.venv/bin/python manage.py check_icons
	.venv/bin/python manage.py service_map --events

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

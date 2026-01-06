.PHONY: install migrate run seed test lint

install:
	python -m pip install -r requirements.txt

migrate:
	python manage.py migrate

seed:
	python manage.py seed_store

run:
	python manage.py runserver

test:
	pytest

lint:
	ruff check .

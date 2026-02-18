.PHONY: generate codegen lint test setup fetch-schema explore clean-generated

setup:
	uv pip install -e ".[test,dev]"
	uv run pre-commit install

fetch-schema:
	uv run python3 scripts/convert_schema.py --fetch

generate: fetch-schema
	uv run ariadne-codegen

codegen:
	uv run python3 scripts/convert_schema.py
	uv run ariadne-codegen

lint:
	uv run pre-commit run --all-files

test:
	uv run pytest

explore:
	uv run python3 scripts/explore.py $(Q)

clean-generated:
	rm -rf deezer_python_gql/generated

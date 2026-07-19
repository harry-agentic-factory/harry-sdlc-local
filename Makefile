VERSION := $(shell cat VERSION)

.PHONY: install test migrate version
install:  ## Symlink l'engine dans ~/.claude
	@bash install.sh

test:  ## Tests du cœur déterministe
	cd tooling && python3 -m pytest

version:
	@echo harry-sdlc-local $(VERSION)

# Migre la data d'un projet vers la version d'engine courante.
# Usage : make migrate PROJECT=HIA   (ou WORKSPACE=/chemin/vers/<projet>-sdlc-local)
migrate:
	cd tooling && python3 -m sdlc.cli $(if $(PROJECT),--project $(PROJECT)) migrate $(if $(WORKSPACE),--workspace $(WORKSPACE))

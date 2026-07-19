VERSION := $(shell cat VERSION)

.PHONY: install test migrate version
install:  ## Symlink l'engine dans ~/.claude
	@bash install.sh

test:  ## Tests du cœur déterministe
	cd tooling && python3 -m pytest

version:
	@echo harry-sdlc-local $(VERSION)

# Migre la data d'un projet vers la version d'engine courante.
# Usage : make migrate PROJECT=SAMPLE   (ou WORKSPACE=/chemin/vers/<projet>-sdlc-local)
migrate:
	cd tooling && python3 -m sdlc.cli $(if $(PROJECT),--project $(PROJECT)) migrate $(if $(WORKSPACE),--workspace $(WORKSPACE))

projects:  ## Liste les projets enregistrés
	cd tooling && python3 -m sdlc.cli projects

# Initialise un nouveau repo data + l'enregistre.
# Usage : make new-project PREFIX=OTHER DIR=../../other-proj/other-proj-sdlc-local REPOS=other-proj-ui,other-proj-brain
new-project:
	cd tooling && python3 -m sdlc.cli init-project $(PREFIX) --path $(DIR) $(if $(REPOS),--repos $(REPOS))

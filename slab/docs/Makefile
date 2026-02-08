# Makefile for Sphinx documentation
#
# MCUemu Documentation Build
# Copyright (C) 2026 Twisted Wires Security Lab

SPHINXOPTS    ?= -W --keep-going
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build

# Default target
.PHONY: help
help:
	@echo "MCUemu Documentation Build Targets:"
	@echo ""
	@echo "  html       - Build HTML documentation"
	@echo "  pdf        - Build PDF documentation (requires LaTeX)"
	@echo "  clean      - Remove build artifacts"
	@echo "  livehtml   - Auto-rebuild on changes (requires sphinx-autobuild)"
	@echo "  images     - Generate architecture diagrams"
	@echo "  linkcheck  - Check external links"
	@echo ""
	@echo "Requirements:"
	@echo "  pip install sphinx furo myst-parser sphinx-copybutton"

.PHONY: html
html: images
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)
	@echo ""
	@echo "Build finished. Open $(BUILDDIR)/html/index.html"

.PHONY: pdf
pdf: images
	$(SPHINXBUILD) -b latex "$(SOURCEDIR)" "$(BUILDDIR)/latex" $(SPHINXOPTS)
	cd $(BUILDDIR)/latex && make
	@echo ""
	@echo "Build finished. PDF at $(BUILDDIR)/latex/mcuemu.pdf"

.PHONY: clean
clean:
	rm -rf $(BUILDDIR)

.PHONY: livehtml
livehtml: images
	sphinx-autobuild "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)

.PHONY: linkcheck
linkcheck:
	$(SPHINXBUILD) -b linkcheck "$(SOURCEDIR)" "$(BUILDDIR)/linkcheck" $(SPHINXOPTS)

.PHONY: images
images:
	@echo "Generating architecture diagrams..."
	@python3 generate_diagrams.py || echo "Diagram generation skipped"

.PHONY: install-deps
install-deps:
	pip install sphinx furo myst-parser sphinx-copybutton sphinx-autobuild

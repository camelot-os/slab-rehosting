# Configuration file for the Sphinx documentation builder.
#
# STM32H563 TrustZone CDC ACM - Documentation
# ANSSI Compliant Secure Embedded System

import os
import sys

# -- Project information -----------------------------------------------------
project = 'STM32H563 TrustZone CDC ACM'
copyright = '2026, Security Research Project'
author = 'Security Research Team'
release = '1.0.0'

# -- General configuration ---------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.todo',
    'sphinx.ext.viewcode',
    'sphinx.ext.graphviz',
    'sphinxcontrib.tikz',  # TikZ diagrams support
]

# TikZ configuration
tikz_proc_suite = 'pdf2svg'
tikz_tikzlibraries = 'arrows.meta,positioning,shapes.geometric,fit,backgrounds,calc'
tikz_latex_preamble = r'''
\usepackage{xcolor}
\definecolor{securegreen}{RGB}{34,139,34}
\definecolor{nscyellow}{RGB}{255,193,7}
\definecolor{nsred}{RGB}{220,53,69}
\definecolor{trustzoneblue}{RGB}{0,123,255}
'''

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']

# -- Options for LaTeX output ------------------------------------------------
latex_elements = {
    'preamble': r'''
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning,shapes.geometric,fit,backgrounds,calc}
''',
}

# -- Extension configuration -------------------------------------------------
todo_include_todos = True

# -- Custom CSS --------------------------------------------------------------
html_context = {
    'css_files': ['_static/custom.css'],
}

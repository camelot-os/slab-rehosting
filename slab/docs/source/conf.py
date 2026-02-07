# Configuration file for the Sphinx documentation builder.
#
# MCUemu - Generic MCU Emulation Platform
# Professional Documentation
#

import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath('../../python'))

# -- Project information -----------------------------------------------------

project = 'MCUemu'
copyright = f'{datetime.now().year}, TwistedWires Security Lab'
author = 'Mathieu Renard'
release = '1.0.0'
version = '1.0'

# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'sphinx.ext.todo',
    'sphinx.ext.graphviz',
    'sphinx_copybutton',
    'myst_parser',
]

# MyST parser settings
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
]

templates_path = ['_templates']
exclude_patterns = []

# Source file extensions
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

# The master toctree document
master_doc = 'index'

# -- Options for HTML output -------------------------------------------------

html_theme = 'furo'
html_static_path = ['_static']

# Logo and favicon (optional, only if files exist)
_logo = os.path.join(os.path.dirname(__file__), '_static', 'mcuemu_logo.png')
_favicon = os.path.join(os.path.dirname(__file__), '_static', 'favicon.ico')
if os.path.exists(_logo):
    html_logo = '_static/mcuemu_logo.png'
if os.path.exists(_favicon):
    html_favicon = '_static/favicon.ico'

html_theme_options = {
    "light_css_variables": {
        "color-brand-primary": "#2563eb",
        "color-brand-content": "#1d4ed8",
    },
    "dark_css_variables": {
        "color-brand-primary": "#60a5fa",
        "color-brand-content": "#93c5fd",
    },
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
}

html_title = "MCUemu Documentation"

# -- Extension configuration -------------------------------------------------

# Napoleon settings
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True

# Autodoc settings
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__'
}

autosummary_generate = True

# Intersphinx mapping
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'asyncio': ('https://docs.python.org/3/library/asyncio.html', None),
}

# Todo extension
todo_include_todos = True

# Graphviz settings
graphviz_output_format = 'svg'

# -- Custom CSS --------------------------------------------------------------

def setup(app):
    app.add_css_file('custom.css')

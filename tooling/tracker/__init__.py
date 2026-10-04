"""Tracker bridge — keeps an external issue tracker (Trello, ...) and the SDLC in step.

The SDLC core knows nothing about the tracker: this package reads story statuses through the `sdlc`
CLI and keeps its own persistence under `<workspace>/_tracker/` (config.json + links.json).
"""

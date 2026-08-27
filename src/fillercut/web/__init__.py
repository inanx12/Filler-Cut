"""v1.0 web UI — localhost FastAPI uygulaması (DESIGN.md §8, Dilim 1).

Paket, v0.3 interaktif review sunucusunun (``report/review_server.py``)
evrimidir: stdlib ``http.server`` SSE + routing'de yetersiz kaldığı için
FastAPI/uvicorn'a taşındı. Arayüz statik HTML + vanilla JS + tek CSS'tir —
şablon motoru / htmx / npm YOK (handoff kararı).
"""

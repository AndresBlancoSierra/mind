<p align="center">
  <a href="https://github.com/AndresBlancoSierra/mind">
    <img src="https://raw.githubusercontent.com/AndresBlancoSierra/mind/main/profile.svg" alt="MIND — mind@arch">
  </a>
</p>

# MIND

Plataforma de **masterización de conocimiento automatizada** (Fase 1: buscar,
descargar, procesar y filtrar con IA local). Pipeline de búsqueda + extracción
+ OCR + filtrado con IA local, con API y app web.

Python 3.12 + SQLAlchemy (async) + frontend React.

---

## 🚀 Cómo correrlo

```bash
cd ~/Proyects/mind
uv run mind --help      # CLI
uv run mind serve       # API + app web
```

---

## 📁 Estructura

```
mind/
├── src/mind/           ← api, cli, download, extract, ocr, filter, search, pipeline
├── mind-app/           ← frontend React (Vite)
├── config/             ← configuración
├── data/               ← datos descargados/procesados
├── tests/
└── docs/               ← documentación del proyecto
```

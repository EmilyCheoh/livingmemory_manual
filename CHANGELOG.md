# Changelog

All notable changes to `livingmemory_manual` will be documented in this file.

## [1.2.0] - 2026-02-27

### Changed
- **Removed redundant `canonical_summary` and `persona_summary` from metadata**: After a full source-code audit of `livingmemory`'s retrieval and injection pipeline, confirmed that these two fields are never used anywhere in the system:
  - **Retrieval** (BM25 + Faiss vector): Only the `content` parameter passed to `add_memory()` is indexed. `canonical_summary` and `persona_summary` sit inertly inside the metadata JSON and are never searched against.
  - **Injection** (`format_memories_for_injection`): Only reads `content`, `topics`, `key_facts`, `importance`, and `participants`. Neither `canonical_summary` nor `persona_summary` is accessed.
  - In the auto-summarization path, `text` and `canonical_summary` were identical because `_build_storage_format()` sets `content = canonical_summary` before calling `add_memory()`. For `/lmput`, the redundancy was pure waste.
- **Schema version bumped to `v3`**: Metadata written by this version no longer contains `canonical_summary`, `persona_summary`, or `summary_quality` fields.
- **Simplified `/lmput` help text**: Removed mention of `canonical_summary` and `persona_summary` from usage instructions. Only five fields matter: `text`, `topics`, `key_facts`, `sentiment`, `importance`.
- **Updated HTML Composer**: Removed the Persona Summary section from the `/lmput` tab. The LLM prompt template no longer requests `persona_summary` output.

## [1.1.0] - 2026-02-23

### Added
- **Memory Type Support (`memory_type`)**: Both `/lmput` and `/lmadd` now accept an optional `memory_type` parameter, stored as `metadata["memory_type"]` to match the upstream LivingMemory convention. Defaults to `GENERAL` when not specified. Known presets: `GENERAL`, `PREFERENCE`, `PLAN`; arbitrary custom types are also accepted.
  - `/lmput`: Include `"memory_type": "PREFERENCE"` in the JSON payload.
  - `/lmadd`: Append the type after importance, e.g. `/lmadd <text> 0.9 PREFERENCE`.
- **HTML Composer Update**: Added Memory Type selector with quick-select buttons (GENERAL / PREFERENCE / PLAN) and custom type input to both `/lmput` and `/lmadd` tabs. Updated the LLM prompt template to include `memory_type` in the output format.

## [1.0.2] - 2026-02-23

### Fixed
- **FAISS Database Connection Loss (`AssertionError`)**: Added a defensive `_ensure_db_connection()` routine that probes into the `MemoryEngine` internals prior to inserting memories. If the underlying `FaissVecDB`'s SQLite `DocumentStorage.engine` is unexpectedly `None` (e.g., due to background cleanup, connection dropping, or hot reloading), it will silently reinitialize the connection automatically. This prevents the `Database connection is not initialized` crash and ensures uninterrupted memory saving.

## [1.0.1] - 2026-02-22

### Added
- **LLM-powered Memory Analysis for `/lmadd`**: Integrated AstrBot's `ProviderManager` to automatically analyze raw manually inserted text. It calls the configured Chat Completion LLM to precisely extract `topics`, `key_facts`, and `sentiment`—matching the quality of auto-summarized memories.
- **`/lmput` Command**: Introduced a zero-API-cost method to gain perfect manual control over every metadata field using raw JSON blocks.
- **LivingMemory Composer Tool**: Added `lmput_composer.html`, a fully self-contained, offline HTML tool with glassmorphism UI to validate inputs and compose `/lmput` JSON parameters interactively.
- **Importance Fine-Tuning**: Both `/lmadd` and `/lmput` now support an optional `importance` parameter (0.0 to 1.0) overriding the configured defaults. Added an interactive slider for it in the HTML composer.

### Fixed
- **AstrBot v4.15.0 Schema Parsing Error**: Fixed an `AttributeError` by converting `_conf_schema.json` from a JSON array to AstrBot v4.15.0's expected dictionary format.
- **Plugin Discovery Mechanism**: Resolved `star_manager` missing API error. Ported plugin resolution to `Context.get_all_stars()` and `Context.get_registered_star()`.
- **RAG Consistency (Canonical Summary)**: Automated `canonical_summary` concatenation as `text | key_fact1；key_fact2` to strictly comply with `livingmemory`'s initial embedding behavior, maximizing `Faiss` BM25 hit rates without the user having to assemble it themselves.

## [1.0.0] - 2026-02-19

### Initial Release
- **Core Injection mechanism**: Designed `_discover_memory_engine()` to find runtime instances of `livingmemory`.
- **`/lmadd` command**: Basic implementation bypassing Milvus directly to Faiss, SQLite, and FTS5 without overhead.

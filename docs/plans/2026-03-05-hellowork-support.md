# Hellowork Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add full Hellowork automation (manual login, search scraping, internal apply with recruiter message, skip external recruiter site button).

**Architecture:** Extend current multi-platform flow in `main.py` with a dedicated `hellowork` branch. Keep scraping/apply platform-specific and reuse existing letter generation + logging utilities. Avoid CV upload interactions.

**Tech Stack:** Python, Playwright sync API, unittest.

---

### Task 1: Platform detection and URL rules

**Files:**
- Modify: `main.py`
- Test: `tests/test_hellowork_platform.py`

1. Write failing tests for Hellowork platform detection and direct offer URL detection.
2. Run targeted tests and confirm failure.
3. Implement minimal detection helpers in `main.py`.
4. Re-run tests and confirm pass.

### Task 2: Hellowork search scraping

**Files:**
- Modify: `main.py`
- Test: `tests/test_hellowork_platform.py`

1. Write failing test for Hellowork search extraction filtering only offer URLs.
2. Run tests and confirm failure.
3. Implement `extraire_offres_page_hellowork` + `recuperer_toutes_offres_hellowork`.
4. Re-run tests and confirm pass.

### Task 3: Hellowork apply flow

**Files:**
- Modify: `main.py`

1. Implement manual login function `se_connecter_hellowork`.
2. Implement `postuler_offre_hellowork`:
   - open offer URL,
   - skip if external recruiter button exists,
   - open recruiter message block,
   - fill motivation letter,
   - submit with `Postuler`,
   - log success/skip.
3. Wire branch in main run loop (login, collect, apply).

### Task 4: Verification

**Files:**
- Test: `tests/*`

1. Run `python -m unittest discover -s tests -p test_hellowork_platform.py`.
2. Run `python -m unittest discover -s tests`.
3. Confirm no regressions.
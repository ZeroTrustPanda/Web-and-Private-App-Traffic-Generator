# Zscaler Lab — Persona Traffic Generator

A self-contained desktop application that generates realistic browser traffic for Zscaler lab tenants using selectable personas, configurable private app FQDNs, and policy-challenging user behaviors.

Each instance runs independently on a single machine (Windows or Linux). No controller VM, no shared-folder orchestration.

---

## Features

- **4 built-in personas**: Nurse, Marketing, Radiology, Doctors — each with unique browsing patterns, site lists, and behavioral weights
- **Realistic browsing**: Full Chromium browser via Playwright with scrolling, link clicking, tab management, search engine usage, and randomized dwell times
- **Policy challenge behaviors**: AI tool access, restricted-geography sites, TLS certificate tests, phishing simulation pages, EICAR malware download tests
- **Private app testing**: GUI-defined internal FQDNs with allow/deny per persona
- **Result classification**: Automatic detection of Zscaler block pages, warnings, redirects, timeouts, DNS failures
- **Local logging**: JSONL event logs, periodic summaries, error logs, automatic screenshots on block/warning/failure
- **Run modes**: Mixed Realistic, Public Only, Private App Focus, Policy Challenge Focus
- **Behavior intensity**: Low / Medium / Aggressive controls how frequently challenge behaviors occur
- **Feature toggles**: Enable/disable AI tests, geo tests, TLS tests, phishing, malware, private apps independently

---

## Requirements

- **Python 3.10+** (3.11 or 3.12 recommended)
- **Playwright** (installed via pip)
- A display (the browser runs in headed mode — not headless)

### Windows

```cmd
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

### Linux (Ubuntu/Debian)

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-tk
pip3 install -r requirements.txt
python3 -m playwright install chromium
python3 -m playwright install-deps
```

### Linux (RHEL/Fedora)

```bash
sudo dnf install -y python3 python3-pip python3-tkinter
pip3 install -r requirements.txt
python3 -m playwright install chromium
python3 -m playwright install-deps
```

---

## Quick Start

```bash
cd traffic_generator
python main.py          # Windows
python3 main.py         # Linux
```

1. Select a persona from the dropdown
2. Choose a run mode and intensity
3. Toggle feature flags as needed
4. Click **Start**
5. Watch the status panel update in real time
6. Click **Stop** when finished
7. Check `logs/` and `screenshots/` for results

---

## Directory Structure

```
traffic_generator/
  main.py                        # Entry point
  requirements.txt

  app/
    gui/main_window.py           # Tkinter GUI
    core/
      config_manager.py          # Loads all JSON config
      run_session.py             # Main async run loop
      state_machine.py           # Lifecycle state machine
    engine/
      behavior_engine.py         # Selects next action type/target
      browser_manager.py         # Playwright browser control
      action_executor.py         # Executes action plans
      result_classifier.py       # Classifies allowed/blocked/etc.
    logging/loggers.py           # Event, summary, error, screenshot
    models/models.py             # All data models and enums
    utils/helpers.py             # Time, random, file, validation

  config/
    global_settings.json
    private_apps.json
    safe_prompts.json
    malware_tests.json
    personas/
      nurse.json
      marketing.json
      radiology.json
      doctors.json

  logs/                          # JSONL event logs, summaries
  screenshots/                   # Auto-captured on block/warn/fail
```

---

## Configuration

### Global Settings (`config/global_settings.json`)

| Setting | Default | Description |
|---------|---------|-------------|
| `page_timeout_ms` | 30000 | Navigation timeout per page |
| `max_actions_before_browser_restart` | 100 | Browser restart interval |
| `browser_relaunch_retry_count` | 3 | Recovery attempts on crash |
| `default_run_mode` | mixed_realistic | Initial run mode |
| `default_behavior_intensity` | medium | Initial intensity |

### Personas (`config/personas/*.json`)

Each persona JSON includes:
- Top-level weights (normal / gray_area / violation)
- Nested violation weights (ai / restricted_geo / tls / phish / malware)
- Behavior tuning (dwell times, click depth, tab chance, etc.)
- 50 legitimate sites, 15 restricted-geo sites, 5 TLS test sites
- 5 phishing simulation targets, 3-5 AI tools, 20 search queries

### Private Apps (`config/private_apps.json`)

Define internal app FQDNs with allowed persona lists. The GUI also supports adding/removing/saving apps at runtime.

### Safe Prompts (`config/safe_prompts.json`)

Synthetic AI prompts per persona. No PHI, no real data. Used when testing AI tool access.

### Malware Tests (`config/malware_tests.json`)

EICAR test file URLs only. The app navigates to the download URL — it never executes downloaded files.

---

## Run Modes

| Mode | Description |
|------|-------------|
| **Mixed Realistic** | Normal browsing + periodic gray-area + violations |
| **Public Only** | Only legitimate public sites (AI tools optional) |
| **Private App Focus** | Heavy private-app checking + some public for realism |
| **Policy Challenge** | Mostly violations: AI, geo, TLS, phish, malware, denied apps |

---

## Behavior Intensity

| Level | Challenge Frequency |
|-------|-------------------|
| Low | Every 20–30 actions |
| Medium | Every 8–12 actions |
| Aggressive | Every 4–6 actions |

---

## Deploying on Multiple VMs

Install identically on each VM. Configure each with a different persona or different private app list. Each VM operates independently — no coordination needed.

---

## Packaging (Future)

The project structure is PyInstaller-ready:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed main.py
```

---

## Non-Goals

This application does **not**:
- Log into any service (no SSO, no MFA, no stored credentials)
- Execute malware payloads
- Scrape authenticated resources
- Act as a real attack tool
- Coordinate multiple VMs centrally

It is a **lab traffic generator** for Zscaler policy validation only.

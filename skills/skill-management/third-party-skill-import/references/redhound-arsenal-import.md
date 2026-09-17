# RedHound Arsenal: curated import record

## Source assessed

- Repository: `https://github.com/jph4cks/redhound-arsenal`
- Default branch: `main`
- Repository metadata observed: 76 `SKILL.md` files, MIT repository license, last push 2026-05-18.
- Content volume: about 1.01 MB across Skill Markdown files.

## Assessment result

The repository is a collection of agent instructions for external security tools, not a tool distribution. It is suitable for selective import only. Bulk import was rejected because it adds overlapping triggers and includes C2, phishing, wireless, evasion, credential, and broad offensive workflows.

Repository-wide screening found 13 pipe-to-shell-style examples concentrated in `chainsaw`, `gtfobins`, `pacu`, `peass-ng`, and `rustscan`. Those were not imported.

## Imported subset

Installed under `skills/security/redhound-arsenal/`:

- `nmap`
- `ffuf`
- `feroxbuster`
- `burpsuite`
- `binwalk`
- `tcpdump`
- `wireshark`

Each source-derived Skill received a local constraints section requiring explicit authorization, minimal evidence-driven actions, bounded scope, and stopping after decisive evidence. The relevant local executables and discovery index were verified after import.

## Compatibility exception

The local `httpx` command was the Python HTTP client package (`python3-httpx`), not ProjectDiscovery HTTPX. The upstream `httpx` Skill was intentionally not imported because its CLI flags would be incompatible. If ProjectDiscovery HTTPX is later installed, use a distinct local name such as `httpx-pd` and adapt the Skill's command references before enabling it.

## Dependency note

The imported Web fuzzing Skills commonly use SecLists. It was already present locally; do not assume its large wordlist package is installed on other hosts.
# Setting up on Windows

LibreLane runs on Linux and macOS. On Windows the supported path is **WSL 2**.
This document covers two routes:

- **Route A — WSL 2 + Nix** (recommended, and the route `flow/run.py` assumes)
- **Route B — Docker container** (fallback)

> **Provenance note.** Every command below is taken from the upstream LibreLane
> documentation and repository at tag `3.0.11`. None of it was executed on the
> machine that wrote it: `wsl.exe` is blocked there by local security policy.
> Treat this file as authoritative-but-unverified and expect to hit small
> environment differences on first run. If you hit one, fix it here too.

---

## Route A — WSL 2 + Nix

### A1. WSL 2

Windows 10 version 2004 (build 19041) or later. In PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
wsl --list --verbose
```

You want `VERSION` to read `2` for your distro.

> **Do not run `wsl --shutdown`.** It terminates *every* distro on the machine,
> including ones belonging to other projects. If you need to stop your own
> distro only, use `wsl --terminate <distro-name>`.

LibreLane's documented minimum is a quad-core 2 GHz CPU and 8 GiB RAM; 16 GiB
is recommended. A full Ibex RTL-to-GDS run is the long pole — budget about an
hour and do not let the machine sleep mid-run.

### A2. Nix

Inside the Ubuntu shell. Do **not** install Nix from `apt` — the packaged
version is usually far too old.

```bash
sudo apt-get update && sudo apt-get install -y curl

curl --proto '=https' --tlsv1.2 -fsSL https://artifacts.nixos.org/nix-installer \
  | sh -s -- install --no-confirm --extra-conf "
    extra-substituters = https://nix-cache.fossi-foundation.org
    extra-trusted-public-keys = nix-cache.fossi-foundation.org:3+K59iFwXqKsL7BNu6Guy0v+uTlwsxYQxjspXzqLYQs=
    extra-experimental-features = nix-command flakes
"
```

The `--extra-conf` block is the important part: it registers the FOSSi
Foundation binary cache, which is what turns a multi-hour source build into a
roughly ten-minute download of prebuilt EDA tools.

Close the terminal and reopen it after this step so the daemon and shell
environment pick up the new configuration.

### A3. Get the environment

```bash
git clone https://github.com/PostOakLabs/openeda-decision-dataset.git
cd openeda-decisions
nix develop
```

The first `nix develop` pulls LibreLane 3.0.11 and its toolchain from the FOSSi
cache and takes a while. Subsequent entries are fast.

Verify:

```bash
librelane --version
librelane --smoke-test
```

`nix develop` also generates `flake.lock` the first time it runs. **Commit
it.** The manifest generator reads its hash into every run manifest, so a run
without a committed lock is not reproducible.

### A4. The PDK

The PDK is fetched by `ciel` (the FOSSi PDK version manager, bundled with
LibreLane). This repository pins the sky130 revision in `pdk/sky130.pin`;
it is the same commit LibreLane 3.0.11 pins in its own `pdk_hashes.yaml`.

```bash
export PDK_ROOT="$PWD/.ciel"
ciel enable --pdk sky130 --pdk-root "$PDK_ROOT" \
  8afc8346a57fe1ab7934ba5a6056ea8b43078e71
```

`flow/run.py` runs exactly this for you and records what it did in the run
manifest. If you enable it by hand, keep `PDK_ROOT` pointing inside the
repository checkout so the PDK is pinned per project rather than per user.

### A5. Quick check that the whole stack works

```bash
librelane --run-example spm
```

---

## Route B — Docker

Use this if Nix will not install, or if you want the flow sandboxed.

The LibreLane flake can build a container image directly:

```bash
nix build .#librelane-docker
docker load < result
docker images librelane
```

That produces an image tagged `librelane:tmp-x86_64-linux`. Run the flow with
the working directory and the PDK both mounted, as your own uid so produced
files are not owned by root:

```bash
docker run --rm -it \
  -v "$PWD":/work -w /work \
  -v "$PDK_ROOT":"$PDK_ROOT" \
  -e PDK_ROOT="$PDK_ROOT" \
  -u "$(id -u)":"$(id -g)" \
  librelane:tmp-x86_64-linux \
  librelane --version
```

Caveats with this route:

- Reproducibility is weaker than Route A. The image is built from the same
  flake, but the container is not the pinned dev shell, so tool versions can
  drift from what `nix develop` would give you.
- Runs are slower than native execution under WSL 2.
- `flow/run.py` assumes Route A by default. To use Docker you invoke the flow
  inside the container yourself; the extractor and manifest tooling are plain
  Python and work the same either way.

---

## Verification checklist

Before generating episodes, confirm all of these:

- [ ] `librelane --version` reports 3.0.11
- [ ] `librelane --smoke-test` passes
- [ ] `flake.lock` exists and is committed
- [ ] `.ciel/sky130A` exists and matches the hash in `pdk/sky130.pin`
- [ ] `python flow/run.py --design ibex --config designs/ibex/config.yaml` completes
- [ ] `python -m pytest` passes

If the fourth item is missing, every metric the extractor reports is worthless,
so check it before trusting any number.

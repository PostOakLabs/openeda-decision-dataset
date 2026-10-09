# SPDX-License-Identifier: Apache-2.0
#
# Pinned environment for openeda-decisions.
#
# This flake does not build LibreLane itself -- it consumes LibreLane's own
# published flake at a fixed tag and re-exports its development shell. That
# keeps the pin to exactly one thing (a LibreLane release) instead of trying
# to re-pin the whole tool zoo (Yosys, OpenROAD, Magic, Netgen, KLayout,
# OpenSTA) by hand.
{
  description = "Pinned LibreLane + sky130A environment for openeda-decisions";

  inputs = {
    # Bump this tag deliberately. Every run manifest records
    # environment.librelane_version, so a bump invalidates prior episodes'
    # provenance and should be a reviewed change, not a lockfile refresh.
    librelane.url = "github:librelane/librelane/3.0.11";
  };

  outputs =
    { self, librelane }:
    let
      # Only claim systems LibreLane actually publishes. Filtering against the
      # upstream attribute set means a system missing upstream is skipped
      # rather than throwing during evaluation.
      wanted = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      available = builtins.attrNames librelane.legacyPackages;
      systems = builtins.filter (s: builtins.elem s available) wanted;

      forEachSystem =
        f:
        builtins.listToAttrs (
          map (system: {
            name = system;
            value = f { pkgs = librelane.legacyPackages.${system}; };
          }) systems
        );
    in
    {
      devShells = forEachSystem (
        { pkgs }:
        {
          # `nix develop` gives a shell where `librelane --version` works.
          # PDK_ROOT is deliberately NOT set here: devshell env values are
          # emitted literally, and a wrong absolute path would be worse than
          # an unset one. Export it in your shell (see docs/windows-setup.md)
          # or let flow/run.py set it for you -- it does, always.
          default = pkgs.librelane-shell.override {
            extra-packages = with pkgs; [
              git
              cacert
            ];
          };
        }
      );

      packages = forEachSystem ({ pkgs }: {
        inherit (pkgs.python3.pkgs) librelane;
        default = pkgs.python3.pkgs.librelane;
      });
    };
}

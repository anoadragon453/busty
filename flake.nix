# A Nix flake that sets up a complete busty development environment.
#
# You must have already installed Nix (https://nixos.org) on your system
# to use this, as well as enabled the flakes feature. The Nix Determinate
# Installer will do both for you:
# https://github.com/DeterminateSystems/nix-installer#the-determinate-nix-installer
#
# To use, run `nix develop --impure` and you'll be dropped into a shell
# with all dependencies installed!

{
  inputs = {
    # Use the master/unstable branch of nixpkgs. Used to fetch the latest
    # available versions of packages.
    nixpkgs.url = "github:NixOS/nixpkgs/master";
    # Output a development shell for x86_64/aarch64 Linux/Darwin (MacOS).
    systems.url = "github:nix-systems/default";
  };

  outputs = { self, nixpkgs, systems, ... }:
    let
      forEachSystem = nixpkgs.lib.genAttrs (import systems);
    in {
      devShells = forEachSystem (system: {
        default = 
          let
            pkgs = import nixpkgs { inherit system; };
          in
            pkgs.mkShell {
              packages = with pkgs; [
                ffmpeg
                python3
                poetry
                python3Packages.ruff
              ];
              shellHook = ''
                export LD_LIBRARY_PATH="${pkgs.libopus}/lib:$LD_LIBRARY_PATH"
                if [ ! -d .venv ]; then
                  poetry install
                fi
                poetry env activate
              '';
            };
      });
    };
}

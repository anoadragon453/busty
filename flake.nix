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
    # A development environment manager built on Nix. See https://devenv.sh.
    devenv.url = "github:cachix/devenv/v1.0.7";
  };

  outputs = { self, nixpkgs, devenv, systems, ... } @ inputs:
    let
      forEachSystem = nixpkgs.lib.genAttrs (import systems);
    in {
      devShells = forEachSystem (system:
        let
          pkgs = import nixpkgs {
            inherit system;
          };
        in {
          # Everything is configured via devenv - a Nix module for creating declarative
          # developer environments. See https://devenv.sh/reference/options/ for a list
          # of all possible options.
          default = devenv.lib.mkShell {
            inherit inputs pkgs;
            modules = [
              {
                # Configure packages to install.
                # Search for package names at https://search.nixos.org/packages?channel=unstable
                packages = with pkgs; [
                  # Required to process user media downloaded from Discord.
                  ffmpeg
                ];

                # Install Python at a specific version.
                languages.python.enable = true;
                languages.python.package = pkgs.python3;

                # Create a virtualenv from the given requirements file.
                languages.python.venv.enable = true;
                languages.python.venv.requirements =
                  (builtins.readFile ./requirements.txt) + (builtins.readFile ./dev-requirements.txt);
              }
            ];
          };
        });
    };
}

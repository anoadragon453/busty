{
  description = "A Discord bot for playing music and managing media";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    systems.url = "github:nix-systems/default";
  };

  outputs =
    {
      self,
      nixpkgs,
      systems,
    }:
    let
      forEachSystem = nixpkgs.lib.genAttrs (import systems);
    in
    {
      devShells = forEachSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            buildInputs = with pkgs; [
              python313
              uv
              ffmpeg
              libopus
              ruff
              mypy
            ];

            shellHook = ''
              echo "🎵 Busty development environment loaded!"
              echo "Run: uv run python -m busty.main"
            '';

            LD_LIBRARY_PATH =
              with pkgs;
              lib.makeLibraryPath [
                ffmpeg.lib
                libopus
              ];
          };
        }
      );
    };
}

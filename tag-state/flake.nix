{
  description = "depot repo";
  inputs.devshell.url = "github:numtide/devshell";
  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs = { self, flake-utils, devshell, nixpkgs }:
    flake-utils.lib.eachDefaultSystem (system: {
      devShell =
        let
          pkgs = import nixpkgs {
            inherit system;

            overlays = [ devshell.overlays.default ];
          };
        in
        pkgs.devshell.mkShell {
          packages = [
            (pkgs.google-cloud-sdk.withExtraComponents [ pkgs.google-cloud-sdk.components.gke-gcloud-auth-plugin ])
            pkgs.python311
          ];
          commands = [
            {
              name = "icl-auth";
              help = "trigger login flows for all tools that need to be logged in to";
              command = "gcloud auth login";
            }
          ];
          env = [
            {
              name = "USE_GKE_GCLOUD_AUTH_PLUGIN";
              value = "True";
            }
          ];
        };
    });

}

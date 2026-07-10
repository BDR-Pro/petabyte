# Bundled node installers

Copies of `lumaris_agent/install.sh` and `install.ps1`, kept here so they ship
inside `lumaris_api/` and always land at `/opt/lumaris/installers/` on deploy —
which is where the `/install.sh` and `/install.ps1` routes serve them from.

If you edit the agent installers, refresh these copies:
    cp ../../lumaris_agent/install.sh ../../lumaris_agent/install.ps1 .

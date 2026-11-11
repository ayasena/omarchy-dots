# Omarchy customizations

Running log of every Omarchy keybind or customization change. Newest first.
See [README.md](README.md) for the save/commit/push rule.

## 2026-11-11

### Twitch web app (installed)

- Installed with:
  ```bash
  omarchy-webapp-install "Twitch" "https://www.twitch.tv" \
    "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/twitch.png"
  ```
- Files created: `~/.local/share/applications/Twitch.desktop`,
  `~/.local/share/icons/hicolor/256x256/apps/twitch.png`
- **Not tracked by `bin/dotfiles-save`** (it syncs `~/.config` + home
  dotfiles only) — re-run the command above to restore on a new machine.
- No keybind. `SUPER + SHIFT + T` is taken (Activity). Add one in
  `~/.config/hypr/bindings.lua` if wanted:
  `o.bind("SUPER + SHIFT + T", "Twitch", { webapp = "https://www.twitch.tv/" })`

### Google app keybinds removed

- `~/.config/hypr/bindings.lua` unbinds:
  - `SUPER + SHIFT + CTRL + G` — Google Messages
  - `SUPER + SHIFT + P` — Google Photos
  - `SUPER + SHIFT + S` — Google Maps
- Kept `SUPER + SHIFT + Y` — YouTube (deliberate; user wants it).
- Undo: delete the `hl.unbind(...)` lines in `bindings.lua`.
- Committed as `8870237`.

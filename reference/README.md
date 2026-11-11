# Reference — Omarchy customization notes

Instructions and a running log for every Omarchy keybind or customization
change on this machine.

## Rule: dotfiles-affecting changes get committed and pushed

Every Omarchy keybind change or customization that touches anything under
`home/` must be saved, committed, and pushed — never left uncommitted:

```bash
~/dotfiles/bin/dotfiles-save   # sync $HOME into this repo, stages everything
git commit -m "<message>"      # Conventional Commits, e.g. chore(hypr): ...
git push
```

Changes that live outside the tracked set (e.g. web apps installed into
`~/.local/share/applications/`) still get an entry in `customizations.md`,
including the exact command to recreate them on a new machine.

## Workflow

| Command | Purpose |
|---|---|
| `bin/dotfiles-save` | Sync `~/.config/hypr`, Omarchy config, `uwsm` env, `.bashrc`, `.XCompose` into this repo; refresh `manifest/` package lists |
| `bin/dotfiles-apply` | Copy tracked files back into `$HOME`, then `hyprctl reload` + restart the shell |

## What gets recorded

Every entry in `customizations.md` (newest first) states:
1. What changed and why
2. Which file/command it lives in
3. How to undo or recreate it

## Current customizations

See [customizations.md](customizations.md).

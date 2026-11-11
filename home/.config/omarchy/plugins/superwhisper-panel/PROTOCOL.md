# The contract this panel reads

The full daemon protocol, for building your own UI, is in
[docs/CONTROL_PROTOCOL.md](../../../../docs/CONTROL_PROTOCOL.md).

The panel is a client. It talks to a running Superwhisper daemon two ways, and
holds no product knowledge of its own: every list it offers is named by the
daemon, so adding a language or a processing mode needs no change here.

## Control socket

A newline-delimited JSON socket. `status.py` finds it at
`$SUPERWHISPER_RUNTIME/control.sock`, else `$XDG_RUNTIME_DIR/superwhisper/control.sock`,
else the same under `superwhisper-dev`. Send `{"version":1,"command":"<name>"}\n`
and read one JSON line back. A reply carrying `error` is a failure.

| Command | The panel reads |
|---|---|
| `status` | `ready`, `phase`, `last` (`text`, `createdAt`, `audio_seconds`, `release_to_text_ms`, `voiceModelID`, `languageModelID`, `language`, `delivery`) |
| `models_get` | `processing`, and `processingOptions` — `{value,label}` for cloud plus every offline mode whose models are present |
| `general_get` | `config.language`, `config.tone`, and `options` — `languages` and `tones` as `{value,label}`, plus `languageLabel`, the configured language named even when the current mode cannot use it |
| `audio_get` | `config.useDefaultInputDevice`, `config.audioInputDeviceId`, and `devices` (`name`, `description`, `availability`, `ignored`) |
| `history_list` | `items` (`timestamp`, `metaPath`, `audioPath`, `metadata`), `total`, `limit`, `more` — sent with `limit` and, for an older page, `before` |
| `history_stats` | From `recording_stat_lines` in `database/superwhisper.sqlite` beside `recordings`, a row per dictation History saved, never deleted when one is deleted or expires, as the macOS, Windows and iOS apps keep theirs: `enabled` (always true; false from a daemon before the table, with history off), `dictations`, `words`, `spokenMs`, `since`, `today` (the local day), `days` (`date`, `words`, `dictations` for each local day of the last year with a dictation), `hours` (24 counts by local hour) and `modes` (`name`, `dictations`: each processing mode, Cloud, Offline or Offline Lite, from the voice model a dictation used), failures and transcribed files left out. `status.py` shapes them into the snapshot's `stats`, or `null` with nothing counted |

## History, a page at a time

`history_list` takes optional `offset`, `limit` and `before`, and answers with
`{items, total, offset, limit, more}`: dictations newest first, `limit` of them
(50 when none is named, clamped to 1–500) from `offset`, counted among those
whose timestamp is below `before` when that is given. `total` counts every
saved dictation; `more` says whether anything older than the page is left.

The snapshot carries the newest page: `history` (up to 200 rows), the true
`historyTotal`, `historyMore`, and `historyCursor`, the page's oldest timestamp.
`status.py --history-before <historyCursor>` prints the next page alone —
`{ok, history, historyTotal, historyMore, historyCursor}` — which the window
appends when its list nears the end; `--history-offset N` asks by position
instead. The window pages by timestamp, so a dictation made or deleted between
pages moves nothing, and each two-second refresh replaces only the newest page,
keeping the older pages it already drew.

A transcript is carried as a preview: `last.text` up to 2,000 characters and
each history row's `text` up to 4,000, with `truncated` true when there is more.
`status.py --copy-last` copies the whole last dictation, and
`status.py --copy-entry <folder>` a history row's whole transcript, piping it
to `wl-copy`.

A failed dictation is kept in History with the audio it captured: its
metadata has an empty `result` (as the macOS app stores one) and the reason in
`linux.error`. Its row has `failed` true, an empty `text` and `error`; every
other row has `failed` false and `error` empty. The window lists it as
"Failed: <error>" in the error color, never as a transcript, and its copy
action has nothing to copy. **R** retries it: `superwhisper history retry
<timestamp>` (`history_retry`) transcribes the recording again with the current
mode, without pasting, and on success the transcript replaces the failure; a
row that did not fail is refused. The bar panel's mode line does not show it.

A daemon released before paging ignores all three parameters and sends its
newest 50 with no `limit`. `historyMore` is then false and no further page is
asked for; `historyTotal` still counts every dictation (from `total`, or, older
still, `general_get`'s `history.entries`).

## Searching and playing history

`history_list` also takes `query`: only dictations whose transcript contains it,
ignoring case, are listed and paged, read from all of history rather than the
pages a window holds. The answer adds `query` and `matches`, the count of every
match (older than `before`, when that is given). `status.py --history-search
TEXT` prints the first page of matches in the snapshot's row shape —
`{ok, query, matches, history, historyTotal, historyMore, historyCursor}` — and
with `--history-before <historyCursor>` the next. A daemon released before
search ignores `query`; `matches` is then missing and nothing further is asked.
A matched row whose first match lies past the 4,000-character preview carries
the text around that match instead, starting with "…" (`truncated` stays true,
so copying still copies the whole transcript).

Each history row carries `audio` (whether its recording was kept) and
`durationMs`. `history play TIMESTAMP [--from SECONDS] [--speed N]` plays that
recording and exits at its end. It keeps no state: the window pauses by
stopping it and seeks by starting it again from another point, counting the
position itself from when it started.

`processingOptions` and `options` exist so the panel holds no copy of the
daemon's lists. Before them the panel imported Superwhisper's own Python module
by relative path, which only resolved when the plugin sat inside the installed
tree.

## Which install to act on

A release install and a development one run different services, own different
sockets and are driven by different wrappers. `status.py` reports the pair
belonging to the daemon that answered it, and the panel uses those rather than
assuming a release install:

| Field | Meaning |
|---|---|
| `cli` | The wrapper to run commands through, e.g. `~/.local/bin/superwhisper` |
| `serviceUnit` | The unit to start or stop, e.g. `superwhisper.service` |

Both are reported even when nothing is running, named after whichever install is
present on disk, so the panel still has something to start. Acting on the wrong
install is what produces a bare `No such file or directory (os error 2)` from a
binary that was never started.

## Command line

Through the reported `cli`, for changes and for opening settings:

| Action | Command |
|---|---|
| Processing mode | `models select <offline\|offline_lite\|cloud>` |
| Language | `general set language '"<id>"'` |
| Tone | `general set tone '"<id>"'` |
| Microphone | `audio select <device>` |
| Settings | `settings [pane]` |
| Play a dictation | `history play <timestamp> [--from <seconds>] [--speed <n>]` |

The service is started and stopped with `systemctl --user start|stop <serviceUnit>`
(the panel's on/off switch); the switch settles once a snapshot reports
`running` as asked.
Copying the last dictation uses `wl-copy`.

## Compatibility

Adding fields is safe and the panel ignores what it does not read. Removing or
renaming any field above, or any command, is a breaking change for this panel.
`tests/status_contract.py` pins the whole shape against `tools/fake-daemon.py`,
so a contributor can check it without an install.

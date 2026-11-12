-- Keep only your personal input overrides here. Uncommented settings below
-- replace Omarchy's defaults.

-- Natural (inverse) scrolling: content moves with your fingers.
hl.config({
  input = {
    touchpad = {
      scroll_factor = 0.2,
      natural_scroll = true,
    },
  },
})

-- Keyboard layout and options.
-- See https://wiki.hypr.land/Configuring/Basics/Variables/#input
-- hl.config({
--   input = {
--     -- Use multiple keyboard layouts and switch between them with Left Alt + Right Alt.
--     kb_layout = "us,dk,eu",
--     kb_options = "omarchy:shift_caps_compose,grp:alts_toggle",
--
--     -- Use a specific keyboard variant if needed (e.g. intl for international keyboards).
--     kb_variant = "intl",
--
--     -- Change speed of keyboard repeat.
--     repeat_rate = 40,
--     repeat_delay = 250,
--
--     -- Start with numlock on by default.
--     numlock_by_default = true,
--
--     -- Increase sensitivity for mouse/trackpad (default: 0).
--     sensitivity = 0.35,
--
--     -- Turn off mouse acceleration (default: adaptive).
--     accel_profile = "flat",
--
--     touchpad = {
--       -- Use natural (inverse) scrolling.
--       natural_scroll = true,
--
--       -- Use two-finger clicks for right-click instead of lower-right corner.
--       clickfinger_behavior = true,
--
--       -- Control the speed of your scrolling.
--       scroll_factor = 0.4,
--
--       -- Enable the touchpad while typing.
--       disable_while_typing = false,
--
--       -- Left-click-and-drag with three fingers.
--       drag_3fg = 1,
--     },
--   },
-- })

-- App-specific touchpad scroll speeds.
-- o.window("(Alacritty|kitty)", { scroll_touchpad = 1.5 })
-- o.window("foot", { scroll_touchpad = 2.0 })
-- o.window("com.mitchellh.ghostty", { scroll_touchpad = 0.2 })

-- macOS Spaces-style workspace swipe: four-finger horizontal pan on the trackpad.
-- Drag tracks your fingers; release past the threshold (or flick) to switch.
-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Gestures/
hl.gesture({ fingers = 4, direction = "horizontal", action = "workspace", scale = 1.0 })

hl.config({
  gestures = {
    -- Match natural scrolling (already enabled above).
    workspace_swipe_invert = true,
    workspace_swipe_direction_lock = true,
    workspace_swipe_cancel_ratio = 0.35,
    -- Allow swiping onto an empty desktop (Hyprland otherwise has no neighbor to animate to).
    workspace_swipe_create_new = true,
    workspace_swipe_distance = 280,
    workspace_swipe_min_speed_to_force = 45,
  },
})

-- Keep desktops 2–10 around even with no windows — like macOS Spaces you've already created.
for slot = 2, 10 do
  hl.workspace_rule({ workspace = tostring(slot), persistent = true })
end

-- Enable touchpad gestures for moving focus (helpful on scrolling layout).
-- hl.gesture({ fingers = 3, direction = "left", action = function() hl.dispatch(hl.dsp.focus({ direction = "l" })) end })
-- hl.gesture({ fingers = 3, direction = "right", action = function() hl.dispatch(hl.dsp.focus({ direction = "r" })) end })

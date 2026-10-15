// Redraws the game's DS button icons (HUD skill bar, dialogue "A", ...) in each finished frame
// as the keys or controller buttons the player has bound. The icons are found by exact pixel
// match against templates (tools/prompt_templates.py) and redrawn at DS resolution in the
// game's colours, so this works whether the game drew them as BG tiles, sprites or 3D quads.
#pragma once
#include <cstdint>
#include "prompts.h"

namespace hudprompts {
// screens: two 256x192 ARGB8888 buffers (top, bottom), modified in place.
// Returns the number of icons redrawn.
// Icons are also found while the screen or HUD is faded, and redrawn with the same fade.
int apply(uint32_t* top, uint32_t* bottom, const Prompts& prompts);

// Draw `label` with its left edge at x, top at y (12 rows tall) in the colours of `style`.
// Returns the width drawn. Exposed for tests/tools.
struct Style { uint32_t outline, face, light, ink, shade1, shade2; };
int drawLabel(uint32_t* scr, int x, int y, const Label& label, const Style& style);
int labelWidth(const Label& label);
}

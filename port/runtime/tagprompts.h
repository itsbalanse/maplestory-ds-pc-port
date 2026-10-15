// Button prompts in game text: the port rewrites the game's button tags (\[A\], \[START\], …)
// into the glyphs of whatever the player has bound, before the game's own tag expansion.
#pragma once
#include <string>
#include <utility>
#include <vector>

namespace recomp {
using TagReplacements = std::vector<std::pair<std::u16string, std::u16string>>;
// Applied in order to every string the game expands (FUN_02017a70). Empty: original prompts.
void setTagReplacements(TagReplacements r);
}

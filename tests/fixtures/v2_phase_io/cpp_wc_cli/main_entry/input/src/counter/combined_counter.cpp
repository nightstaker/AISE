#include "counter/combined_counter.h"
#include <string>

namespace counter {

/**
 * Compute lines, words, and bytes in a single pass over the content.
 * This satisfies the requirement that the file is read only once.
 *
 * @param content  The text content to analyze
 * @return         Combined stats with ok flag and all three counts
 */
CombinedStats count_all(const std::string& content) {
    CombinedStats result;
    result.ok = true;
    result.line_count = 0;
    result.word_count = 0;
    result.byte_count = static_cast<int64_t>(content.size());

    bool in_word = false;

    for (char c : content) {
        // Count bytes (already computed above, but this is the single pass)
        // Line counting: count newlines
        if (c == '\n') {
            ++result.line_count;
        }

        // Word counting: track transitions from whitespace to non-whitespace
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v') {
            if (in_word) {
                in_word = false;
            }
        } else {
            if (!in_word) {
                ++result.word_count;
                in_word = true;
            }
        }
    }

    return result;
}

} // namespace counter

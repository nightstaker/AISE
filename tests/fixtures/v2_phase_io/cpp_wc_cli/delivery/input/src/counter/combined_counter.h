#pragma once

#include <cstdint>
#include <string>

namespace counter {

struct CombinedStats {
    bool ok;
    int64_t line_count;
    int64_t word_count;
    int64_t byte_count;
};

/**
 * Compute lines, words, and bytes in a single pass over the content.
 * This satisfies the requirement that the file is read only once.
 *
 * @param content  The text content to analyze
 * @return         Combined stats with ok flag and all three counts
 */
CombinedStats count_all(const std::string& content);

} // namespace counter

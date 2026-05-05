#pragma once

#include <string>

namespace counter {

struct WordCountResult {
    bool ok;
    int64_t word_count;
};

/**
 * Count the number of whitespace-separated words in content.
 * @param content  The text content to count words in
 * @return         Result with ok flag and word count
 */
WordCountResult count_words(const std::string& content);

} // namespace counter

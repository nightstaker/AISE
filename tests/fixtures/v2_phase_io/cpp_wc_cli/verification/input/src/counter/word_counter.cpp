#include "counter/word_counter.h"
#include <string>
#include <sstream>

namespace counter {

/**
 * Count the number of whitespace-separated words in content.
 * Words are sequences of non-whitespace characters.
 *
 * @param content  The text content to count words in
 * @return         Result struct with ok flag and word count
 */
WordCountResult count_words(const std::string& content) {
    WordCountResult result;
    result.ok = true;
    result.word_count = 0;

    std::istringstream stream(content);
    std::string word;
    while (stream >> word) {
        ++result.word_count;
    }

    return result;
}

} // namespace counter

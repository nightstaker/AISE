#include "counter/line_counter.h"
#include <string>

namespace counter {

/**
 * Count the number of newline characters in content.
 *
 * @param content  The text content to count lines in
 * @return         Result struct with ok flag and line count
 */
LineCountResult count_lines(const std::string& content) {
    LineCountResult result;
    result.ok = true;
    result.line_count = 0;

    for (char c : content) {
        if (c == '\n') {
            ++result.line_count;
        }
    }

    return result;
}

} // namespace counter

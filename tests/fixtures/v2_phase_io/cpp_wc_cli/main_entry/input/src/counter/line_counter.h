#pragma once

#include <string>

namespace counter {

struct LineCountResult {
    bool ok;
    int64_t line_count;
};

/**
 * Count the number of newline characters in content.
 * @param content  The text content to count lines in
 * @return         Result with ok flag and line count
 */
LineCountResult count_lines(const std::string& content);

} // namespace counter

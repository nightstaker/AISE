#pragma once

#include <string>

namespace counter {

struct ByteCountResult {
    bool ok;
    int64_t byte_count;
};

/**
 * Count the number of bytes in content.
 * @param content  The text content to count bytes in
 * @return         Result with ok flag and byte count
 */
ByteCountResult count_bytes(const std::string& content);

} // namespace counter

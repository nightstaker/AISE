#include "counter/byte_counter.h"
#include <string>

namespace counter {

/**
 * Count the number of bytes in content.
 * This is simply the string length in bytes.
 *
 * @param content  The text content to count bytes in
 * @return         Result struct with ok flag and byte count
 */
ByteCountResult count_bytes(const std::string& content) {
    ByteCountResult result;
    result.ok = true;
    result.byte_count = static_cast<int64_t>(content.size());
    return result;
}

} // namespace counter

#include "output/formatter.h"
#include <string>
#include <sstream>

namespace output {

/**
 * Format the count results as a string for output.
 * Format: "<lines> <words> <bytes> <filename>"
 *
 * @param lines    Number of lines
 * @param words    Number of words
 * @param bytes    Number of bytes
 * @param filename The filename to display
 * @return         Formatted string
 */
std::string format_output(int64_t lines, int64_t words, int64_t bytes,
                          const std::string& filename) {
    std::ostringstream oss;
    oss << lines << " " << words << " " << bytes << " " << filename;
    return oss.str();
}

} // namespace output

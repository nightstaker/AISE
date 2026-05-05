#pragma once

#include <cstdint>
#include <string>

namespace output {

/**
 * Format the count results as a string for output.
 * Format: "<lines> <words> <bytes> <filename>"
 */
std::string format_output(int64_t lines, int64_t words, int64_t bytes,
                          const std::string& filename);

} // namespace output

#pragma once

#include <string>

namespace input {

/**
 * Parse and validate command-line arguments.
 * Expects exactly one argument: the filename to process.
 * @return the validated file path string
 * @throws std::runtime_error if argc != 2 or filename is empty
 */
std::string parse_file_argument(int argc, char* argv[]);

} // namespace input

#pragma once

#include <fstream>
#include <string>

namespace input {

struct FileOpenResult {
    bool ok;
    std::ifstream stream;
    std::string error_message;
};

/**
 * Open a file for reading.
 * @param filename  Path to the file to open
 * @return          Result with ok flag, stream, and optional error message
 */
FileOpenResult open_file(const std::string& filename);

} // namespace input
